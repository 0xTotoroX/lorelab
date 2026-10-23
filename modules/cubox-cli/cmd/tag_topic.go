package cmd

import (
	"fmt"

	"github.com/OLCUBO/cubox-cli/internal/client"
	"github.com/OLCUBO/cubox-cli/internal/config"
	"github.com/OLCUBO/cubox-cli/internal/topic"
	"github.com/spf13/cobra"
)

var (
	topicCardID string
	topicApply  bool
)

var tagTopicCmd = &cobra.Command{
	Use:   "topic",
	Short: "Suggest or add approved topic tags for one card",
	Long: `Classify one card from its parsed content or, when unavailable, a
substantial description. Only existing direct children of the 主题 tag are
eligible. Preview is the default; --apply adds missing approved tags only.
For this single-card command, new topic names are suggestions only.
Use collect, review or auto-review, and backfill for a batch of cards.

Set CUBOX_TOPIC_API_URL to an OpenAI-compatible chat completions URL,
CUBOX_TOPIC_MODEL to the model name, and CUBOX_TOPIC_API_KEY for a remote API.
The card text is sent to this configured model endpoint.`,
	Example: `  cubox-cli tag topic --id 7247925101516031380
  cubox-cli tag topic --id 7247925101516031380 --apply`,
	RunE: runTagTopic,
}

func init() {
	tagTopicCmd.Flags().StringVar(&topicCardID, "id", "", "card ID to classify (required)")
	tagTopicCmd.MarkFlagRequired("id")
	tagTopicCmd.Flags().BoolVar(&topicApply, "apply", false, "add missing approved topic tags after classification")
	tagCmd.AddCommand(tagTopicCmd)
}

func runTagTopic(cmd *cobra.Command, args []string) error {
	cfg, err := config.Load()
	if err != nil {
		return err
	}
	classifier, err := topicClassifier()
	if err != nil {
		return err
	}
	store := client.New(cfg.BaseURL(), cfg.Token)
	result, err := topic.Process(cmd.Context(), store, classifier, topicCardID, topicApply)
	if err != nil {
		return err
	}
	if outputFormat == "text" {
		fmt.Printf("%s: %s (%s)\n", result.CardID, result.Status, result.Evidence)
		fmt.Printf("主题: %v；新增: %v；待审核词: %v\n", result.Topics, result.Added, result.Suggested)
		if result.Reason != "" {
			fmt.Println(result.Reason)
		}
		return nil
	}
	printJSON(result)
	return nil
}
