package cmd

import (
	"encoding/json"
	"fmt"
	"strings"

	"github.com/OLCUBO/cubox-cli/internal/client"
	"github.com/OLCUBO/cubox-cli/internal/config"
	"github.com/spf13/cobra"
)

var (
	tagUpdateID      string
	tagUpdateNewName string

	tagDeleteIDs []string

	tagMergeSourceIDs []string
	tagMergeTargetID  string

	tagMoveID       string
	tagMoveParentID string
)

var tagCmd = &cobra.Command{
	Use:   "tag",
	Short: "Manage tags",
}

var tagListCmd = &cobra.Command{
	Use:   "list",
	Short: "List all tags",
	RunE:  runTagList,
}

var tagUpdateCmd = &cobra.Command{
	Use:   "update",
	Short: "Rename a tag",
	Long: `Rename a tag by ID. The new name applies to the leaf segment
only — nested children stay attached and are reachable through the
new path automatically.

To find a tag's ID, run "cubox-cli tag list".

Examples:
  cubox-cli tag update --id 7295070793040398540 --new-name link
  cubox-cli tag update --id 7295070793040398540 --new-name "Reading List"`,
	RunE: runTagUpdate,
}

var tagDeleteCmd = &cobra.Command{
	Use:   "delete",
	Short: "Delete one or more tags (batch)",
	Long: `Delete one or more tags by ID. Cards previously tagged with the
deleted tag(s) are kept; only the tag-card association is removed.

To merge tags into another tag instead of dropping them, use
"cubox-cli tag merge".

Examples:
  cubox-cli tag delete --id 7444025677600260245
  cubox-cli tag delete --id 7444025677600260245,7443973659296793971`,
	RunE: runTagDelete,
}

var tagMergeCmd = &cobra.Command{
	Use:   "merge",
	Short: "Merge tags into a target tag (batch)",
	Long: `Merge one or more source tags into a target tag. All cards
associated with the source tags are re-tagged onto the target, and
the source tags are then deleted.

Examples:
  cubox-cli tag merge --source 7342187912403881105,7342187917722258501 --target 7247925099053977508`,
	RunE: runTagMerge,
}

var tagMoveCmd = &cobra.Command{
	Use:   "move",
	Short: "Move an existing tag under another tag",
	Long: `Move an existing tag under a parent tag while retaining its ID and
card associations. Both --id and --parent take tag IDs from "tag list".`,
	Example: `  cubox-cli tag move --id 7501950006702640053 --parent 7479207167292083787`,
	RunE:    runTagMove,
}

// ---- tag new / sort (web/app group) ----

var (
	tagNewName   string
	tagNewParent string
	tagSortJSON  string
)

var tagNewCmd = &cobra.Command{
	Use:   "new",
	Short: "Create a tag",
	Long: `Create a tag by name (the leaf name; created on the fly by the app
when tagging too, but this creates it standalone). --parent takes a tag ID
for nesting.`,
	Example: `  cubox-cli tag new --name ai
  cubox-cli tag new --name llm --parent 7123...`,
	RunE: func(cmd *cobra.Command, args []string) error {
		if tagNewName == "" {
			return fmt.Errorf("--name is required")
		}
		cfg, err := config.Load()
		if err != nil {
			return err
		}
		web, err := webClient(cfg)
		if err != nil {
			return err
		}
		raw, err := web.WebTagNew(tagNewName, tagNewParent)
		if err != nil {
			return err
		}
		printJSON(map[string]interface{}{"message": "tag created", "name": tagNewName, "data": jsonRaw(raw)})
		return nil
	},
}

var tagSortCmd = &cobra.Command{
	Use:   "sort",
	Short: "Reorder tags (experimental)",
	Long: `Reorder tags. Experimental: pass the order payload as JSON — the same
shape the web app submits on tag drag & drop.`,
	Example: `  cubox-cli tag sort --json '{"tagId":"7123...","order":["7123...","7456..."]}'`,
	RunE: func(cmd *cobra.Command, args []string) error {
		if tagSortJSON == "" {
			return fmt.Errorf("--json is required")
		}
		var body map[string]interface{}
		if err := json.Unmarshal([]byte(tagSortJSON), &body); err != nil {
			return fmt.Errorf("parsing --json: %w", err)
		}
		cfg, err := config.Load()
		if err != nil {
			return err
		}
		web, err := webClient(cfg)
		if err != nil {
			return err
		}
		raw, err := web.WebPostRaw("/c/api/tag/sort", body)
		if err != nil {
			return err
		}
		printJSON(map[string]interface{}{"message": "tags sorted", "data": jsonRaw(raw)})
		return nil
	},
}

func init() {
	tagUpdateCmd.Flags().StringVar(&tagUpdateID, "id", "", "tag ID to rename (required)")
	tagUpdateCmd.MarkFlagRequired("id")
	tagUpdateCmd.Flags().StringVar(&tagUpdateNewName, "new-name", "", "new leaf name for the tag (required)")
	tagUpdateCmd.MarkFlagRequired("new-name")

	tagDeleteCmd.Flags().StringSliceVar(&tagDeleteIDs, "id", nil, "tag IDs to delete (comma-separated, required)")
	tagDeleteCmd.MarkFlagRequired("id")

	tagMergeCmd.Flags().StringSliceVar(&tagMergeSourceIDs, "source", nil, "source tag IDs to merge (comma-separated, required)")
	tagMergeCmd.MarkFlagRequired("source")
	tagMergeCmd.Flags().StringVar(&tagMergeTargetID, "target", "", "target tag ID to merge into (required)")
	tagMergeCmd.MarkFlagRequired("target")

	tagMoveCmd.Flags().StringVar(&tagMoveID, "id", "", "existing tag ID to move (required)")
	tagMoveCmd.MarkFlagRequired("id")
	tagMoveCmd.Flags().StringVar(&tagMoveParentID, "parent", "", "destination parent tag ID (required)")
	tagMoveCmd.MarkFlagRequired("parent")

	tagNewCmd.Flags().StringVar(&tagNewName, "name", "", "tag name (required)")
	tagNewCmd.Flags().StringVar(&tagNewParent, "parent", "", "parent tag ID for nesting (optional)")
	tagSortCmd.Flags().StringVar(&tagSortJSON, "json", "", "sort payload as JSON (required, experimental)")

	tagCmd.AddCommand(tagListCmd, tagUpdateCmd, tagDeleteCmd, tagMergeCmd, tagMoveCmd, tagNewCmd, tagSortCmd)
	rootCmd.AddCommand(tagCmd)
}

func runTagList(cmd *cobra.Command, args []string) error {
	cfg, err := config.Load()
	if err != nil {
		return err
	}
	c := client.New(cfg.BaseURL(), cfg.Token)
	tags, err := c.ListTags()
	if err != nil {
		return err
	}

	if outputFormat == "text" {
		printTagsText(tags)
		return nil
	}
	printJSON(tags)
	return nil
}

func runTagMove(cmd *cobra.Command, args []string) error {
	cfg, err := config.Load()
	if err != nil {
		return err
	}
	c := client.New(cfg.BaseURL(), cfg.Token)
	tags, err := c.ListTags()
	if err != nil {
		return err
	}
	byID := make(map[string]client.Tag, len(tags))
	for _, tag := range tags {
		byID[tag.ID] = tag
	}
	source, ok := byID[tagMoveID]
	if !ok {
		return fmt.Errorf("source tag %s does not exist", tagMoveID)
	}
	parent, ok := byID[tagMoveParentID]
	if !ok {
		return fmt.Errorf("parent tag %s does not exist", tagMoveParentID)
	}
	if source.ParentID != nil && *source.ParentID == parent.ID {
		return fmt.Errorf("tag %s is already under %s", source.ID, parent.ID)
	}
	seen := make(map[string]bool)
	for ancestor := parent; ; {
		if ancestor.ID == source.ID {
			return fmt.Errorf("cannot move a tag under itself or its descendant")
		}
		if seen[ancestor.ID] {
			return fmt.Errorf("parent chain contains a cycle at tag %s", ancestor.ID)
		}
		seen[ancestor.ID] = true
		if ancestor.ParentID == nil {
			break
		}
		next, exists := byID[*ancestor.ParentID]
		if !exists {
			return fmt.Errorf("parent chain contains unknown tag %s", *ancestor.ParentID)
		}
		ancestor = next
	}
	for _, tag := range tags {
		if tag.ID != source.ID && tag.ParentID != nil && *tag.ParentID == parent.ID && tag.Name == source.Name {
			return fmt.Errorf("destination already contains tag %q", source.Name)
		}
	}
	web, err := webClient(cfg)
	if err != nil {
		return err
	}
	if _, err := web.WebMoveTag(source.ID, parent.ID); err != nil {
		return err
	}
	updated, err := c.ListTags()
	if err != nil {
		return fmt.Errorf("move request succeeded, but verification failed: %w", err)
	}
	for _, tag := range updated {
		if tag.ID == source.ID {
			if tag.ParentID == nil || *tag.ParentID != parent.ID {
				return fmt.Errorf("move request returned success, but tag %s is not under %s", source.ID, parent.ID)
			}
			msg := fmt.Sprintf("Moved tag %s to %s.", source.ID, tag.NestedName)
			if outputFormat == "text" {
				fmt.Println(msg)
			} else {
				printJSON(tagOpResult{Count: 1, Message: msg})
			}
			return nil
		}
	}
	return fmt.Errorf("move request returned success, but tag %s is missing from the tag list", source.ID)
}

type tagOpResult struct {
	Count   int    `json:"count"`
	Message string `json:"message"`
}

func runTagUpdate(cmd *cobra.Command, args []string) error {
	if strings.Contains(tagUpdateNewName, "/") {
		return fmt.Errorf("--new-name must be a single leaf name without \"/\"; nested paths are not supported")
	}

	cfg, err := config.Load()
	if err != nil {
		return err
	}
	c := client.New(cfg.BaseURL(), cfg.Token)

	if err := c.UpdateTag(&client.TagUpdateRequest{
		ID:   tagUpdateID,
		Name: tagUpdateNewName,
	}); err != nil {
		return err
	}

	msg := fmt.Sprintf("Successfully renamed tag %s to %q.", tagUpdateID, tagUpdateNewName)
	if outputFormat == "text" {
		fmt.Println(msg)
		return nil
	}
	printJSON(tagOpResult{Count: 1, Message: msg})
	return nil
}

func runTagDelete(cmd *cobra.Command, args []string) error {
	if len(tagDeleteIDs) == 0 {
		return fmt.Errorf("at least one tag ID is required")
	}

	cfg, err := config.Load()
	if err != nil {
		return err
	}
	c := client.New(cfg.BaseURL(), cfg.Token)

	if err := c.DeleteTags(tagDeleteIDs); err != nil {
		return err
	}

	count := len(tagDeleteIDs)
	msg := fmt.Sprintf("Successfully deleted %d tag(s).", count)
	if outputFormat == "text" {
		fmt.Println(msg)
		return nil
	}
	printJSON(tagOpResult{Count: count, Message: msg})
	return nil
}

func runTagMerge(cmd *cobra.Command, args []string) error {
	if len(tagMergeSourceIDs) == 0 {
		return fmt.Errorf("at least one source tag ID is required")
	}
	for _, id := range tagMergeSourceIDs {
		if id == tagMergeTargetID {
			return fmt.Errorf("--target tag ID %s cannot also appear in --source", id)
		}
	}

	cfg, err := config.Load()
	if err != nil {
		return err
	}
	c := client.New(cfg.BaseURL(), cfg.Token)

	if err := c.MergeTags(&client.TagMergeRequest{
		SourceTagIDs: tagMergeSourceIDs,
		TargetTagID:  tagMergeTargetID,
	}); err != nil {
		return err
	}

	count := len(tagMergeSourceIDs)
	msg := fmt.Sprintf("Successfully merged %d source tag(s) into %s.", count, tagMergeTargetID)
	if outputFormat == "text" {
		fmt.Println(msg)
		return nil
	}
	printJSON(tagOpResult{Count: count, Message: msg})
	return nil
}

func printTagsText(tags []client.Tag) {
	for _, t := range tags {
		depth := strings.Count(t.NestedName, "/")
		indent := strings.Repeat("  ", depth)
		fmt.Printf("%s%s  [%s]\n", indent, t.Name, t.ID)
	}
}
