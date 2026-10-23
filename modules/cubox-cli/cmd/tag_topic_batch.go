package cmd

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"

	"github.com/OLCUBO/cubox-cli/internal/client"
	"github.com/OLCUBO/cubox-cli/internal/config"
	"github.com/OLCUBO/cubox-cli/internal/topic"
	"github.com/spf13/cobra"
)

var (
	topicCollectIDs     []string
	topicCollectOut     string
	topicReviewPlan     string
	topicReviewName     string
	topicReviewDecision string
	topicReviewTarget   string
	topicAutoReviewPlan string
	topicBackfillPlan   string
	topicBackfillApply  bool
	topicBackfillAuto   bool
)

var topicCollectCmd = &cobra.Command{
	Use:   "collect",
	Short: "Collect topic candidates from cards into a local review plan",
	Long: `Read the given cards and group model-suggested topic names by card.
This command writes a local review plan and never changes Cubox tags or cards.`,
	Example: `  cubox-cli tag topic collect --id CARD1,CARD2 --out topic-plan.json`,
	RunE:    runTopicCollect,
}

var topicReviewCmd = &cobra.Command{
	Use:   "review",
	Short: "Record an approval, merge, or rejection in a local topic plan",
	Long: `Mark one collected candidate approved, merged into a canonical topic,
or rejected. Only the local plan file changes. Approved topic names must later
exist as direct children of 主题 before backfill.`,
	Example: `  cubox-cli tag topic review --plan topic-plan.json --name MCP --decision approved
  cubox-cli tag topic review --plan topic-plan.json --name "Agent 工具" --decision merged --target MCP`,
	RunE: runTopicReview,
}

var topicBackfillCmd = &cobra.Command{
	Use:   "backfill",
	Short: "Reclassify reviewed cards and optionally append approved topics",
	Long: `All candidates in the local plan must be reviewed first. Approved and
merged topic names must already exist under 主题. Each card is classified again
from its current content. Preview is the default; --apply appends missing tags.
With --auto, pending candidates may remain; preview shows planned tag creation.
--auto --apply creates approved 主题 tags before appending them to cards.
If an error occurs during --apply, earlier tags or cards may already have changed.`,
	Example: `  cubox-cli tag topic backfill --plan topic-plan.json
  cubox-cli tag topic backfill --plan topic-plan.json --apply`,
	RunE: runTopicBackfill,
}

var topicAutoReviewCmd = &cobra.Command{
	Use:   "auto-review",
	Short: "Merge synonyms and auto-approve repeated, well-supported topics",
	Long: `Use the configured model to compare pending concepts with existing topics
and each other. A new topic is auto-approved only when at least two distinct
cards have substantial article bodies and model-confirmed support. Singletons
and weak evidence remain pending. This command only changes the local plan.`,
	Example: `  cubox-cli tag topic auto-review --plan topic-plan.json`,
	RunE:    runTopicAutoReview,
}

func init() {
	topicCollectCmd.Flags().StringSliceVar(&topicCollectIDs, "id", nil, "card IDs to collect (comma-separated, required)")
	topicCollectCmd.MarkFlagRequired("id")
	topicCollectCmd.Flags().StringVar(&topicCollectOut, "out", "", "new local review plan path (required)")
	topicCollectCmd.MarkFlagRequired("out")
	topicReviewCmd.Flags().StringVar(&topicReviewPlan, "plan", "", "local review plan path (required)")
	topicReviewCmd.MarkFlagRequired("plan")
	topicReviewCmd.Flags().StringVar(&topicReviewName, "name", "", "exact candidate name (required)")
	topicReviewCmd.MarkFlagRequired("name")
	topicReviewCmd.Flags().StringVar(&topicReviewDecision, "decision", "", "approved, merged, or rejected (required)")
	topicReviewCmd.MarkFlagRequired("decision")
	topicReviewCmd.Flags().StringVar(&topicReviewTarget, "target", "", "canonical topic leaf name for approved or merged candidate")
	topicAutoReviewCmd.Flags().StringVar(&topicAutoReviewPlan, "plan", "", "local review plan path (required)")
	topicAutoReviewCmd.MarkFlagRequired("plan")
	topicBackfillCmd.Flags().StringVar(&topicBackfillPlan, "plan", "", "reviewed local plan path (required)")
	topicBackfillCmd.MarkFlagRequired("plan")
	topicBackfillCmd.Flags().BoolVar(&topicBackfillApply, "apply", false, "append approved topics to the plan's cards")
	topicBackfillCmd.Flags().BoolVar(&topicBackfillAuto, "auto", false, "allow pending concepts and create auto-approved topic tags with --apply")
	tagTopicCmd.AddCommand(topicCollectCmd, topicReviewCmd, topicAutoReviewCmd, topicBackfillCmd)
}

func topicClassifier() (*topic.ChatClassifier, error) {
	return topic.NewChatClassifier(
		os.Getenv("CUBOX_TOPIC_API_URL"),
		os.Getenv("CUBOX_TOPIC_API_KEY"),
		os.Getenv("CUBOX_TOPIC_MODEL"),
	)
}

func runTopicCollect(cmd *cobra.Command, args []string) error {
	cfg, err := config.Load()
	if err != nil {
		return err
	}
	classifier, err := topicClassifier()
	if err != nil {
		return err
	}
	plan, err := topic.Collect(cmd.Context(), client.New(cfg.BaseURL(), cfg.Token), classifier, topicCollectIDs)
	if err != nil {
		return err
	}
	if err := saveTopicPlan(topicCollectOut, plan, true); err != nil {
		return err
	}
	printJSON(map[string]interface{}{"plan": topicCollectOut, "cards": len(plan.Cards), "candidates": plan.Candidates})
	return nil
}

func runTopicReview(cmd *cobra.Command, args []string) error {
	plan, err := loadTopicPlan(topicReviewPlan)
	if err != nil {
		return err
	}
	if err := plan.SetReview(topicReviewName, topicReviewDecision, topicReviewTarget); err != nil {
		return err
	}
	if err := saveTopicPlan(topicReviewPlan, plan, false); err != nil {
		return err
	}
	printJSON(map[string]string{"candidate": topicReviewName, "decision": topicReviewDecision, "plan": topicReviewPlan})
	return nil
}

func runTopicAutoReview(cmd *cobra.Command, args []string) error {
	plan, err := loadTopicPlan(topicAutoReviewPlan)
	if err != nil {
		return err
	}
	cfg, err := config.Load()
	if err != nil {
		return err
	}
	classifier, err := topicClassifier()
	if err != nil {
		return err
	}
	report, err := topic.AutoReview(cmd.Context(), client.New(cfg.BaseURL(), cfg.Token), classifier, &plan)
	if err != nil {
		return err
	}
	if err := saveTopicPlan(topicAutoReviewPlan, plan, false); err != nil {
		return err
	}
	printJSON(report)
	return nil
}

func runTopicBackfill(cmd *cobra.Command, args []string) error {
	plan, err := loadTopicPlan(topicBackfillPlan)
	if err != nil {
		return err
	}
	if err := plan.Validate(!topicBackfillAuto); err != nil {
		return err
	}
	cfg, err := config.Load()
	if err != nil {
		return err
	}
	classifier, err := topicClassifier()
	if err != nil {
		return err
	}
	store := client.New(cfg.BaseURL(), cfg.Token)
	if topicBackfillAuto {
		var creator topic.TagCreator
		if topicBackfillApply {
			creator = &lazyTopicCreator{cfg: cfg}
		}
		report, err := topic.AutoBackfill(cmd.Context(), store, creator, classifier, plan, topicBackfillApply)
		if err != nil {
			printJSON(report)
			return err
		}
		printJSON(report)
		return nil
	}
	report, err := topic.Backfill(cmd.Context(), store, classifier, plan, topicBackfillApply)
	if err != nil {
		if topicBackfillApply && report.Applied > 0 {
			printJSON(report)
		}
		return err
	}
	printJSON(report)
	return nil
}

type lazyTopicCreator struct {
	cfg *config.Config
	web *client.Client
}

func (c *lazyTopicCreator) CreateTopicTag(name, parentID string) error {
	if c.web == nil {
		web, err := webClient(c.cfg)
		if err != nil {
			return err
		}
		c.web = web
	}
	return topic.WebTagCreator{Web: c.web}.CreateTopicTag(name, parentID)
}

func loadTopicPlan(path string) (topic.Plan, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return topic.Plan{}, err
	}
	var plan topic.Plan
	if err := json.Unmarshal(data, &plan); err != nil {
		return topic.Plan{}, fmt.Errorf("parsing topic plan: %w", err)
	}
	if err := plan.Validate(false); err != nil {
		return topic.Plan{}, err
	}
	return plan, nil
}

func saveTopicPlan(path string, plan topic.Plan, newOnly bool) error {
	if err := plan.Validate(false); err != nil {
		return err
	}
	data, err := json.MarshalIndent(plan, "", "  ")
	if err != nil {
		return err
	}
	data = append(data, '\n')
	if newOnly {
		file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
		if err != nil {
			return err
		}
		if _, err := file.Write(data); err != nil {
			file.Close()
			os.Remove(path)
			return err
		}
		if err := file.Close(); err != nil {
			os.Remove(path)
			return err
		}
		return nil
	}
	temp, err := os.CreateTemp(filepath.Dir(path), ".topic-plan-*")
	if err != nil {
		return err
	}
	defer os.Remove(temp.Name())
	if err := temp.Chmod(0600); err != nil {
		temp.Close()
		return err
	}
	if _, err := temp.Write(data); err != nil {
		temp.Close()
		return err
	}
	if err := temp.Close(); err != nil {
		return err
	}
	return os.Rename(temp.Name(), path)
}
