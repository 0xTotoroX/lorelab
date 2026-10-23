package cmd

import (
	"fmt"
	"strings"

	"github.com/OLCUBO/cubox-cli/internal/client"
	"github.com/OLCUBO/cubox-cli/internal/config"
	"github.com/OLCUBO/cubox-cli/internal/tagcleanup"
	"github.com/spf13/cobra"
)

var (
	pruneTagID    string
	pruneTagName  string
	pruneTagApply bool
)

var tagPruneCmd = &cobra.Command{
	Use:   "prune-empty",
	Short: "Preview or delete an empty leaf tag",
	Long: `Check that the requested tag has no child tags and no active or
archived cards. Preview is the default; --apply deletes only after rechecking.
The root tags 来源, 处理, skill, 笔记, and 主题 are protected.
Use this command for a tag emptied outside cubox-cli, such as PICSED.`,
	Example: `  cubox-cli tag prune-empty --name PICSED
  cubox-cli tag prune-empty --name PICSED --apply`,
	RunE: runTagPrune,
}

func init() {
	tagPruneCmd.Flags().StringVar(&pruneTagID, "id", "", "exact tag ID")
	tagPruneCmd.Flags().StringVar(&pruneTagName, "name", "", "exact nested tag name, such as PICSED or 来源/Pixiv")
	tagPruneCmd.Flags().BoolVar(&pruneTagApply, "apply", false, "delete the tag after checking it is empty")
	tagCmd.AddCommand(tagPruneCmd)
}

func runTagPrune(cmd *cobra.Command, args []string) error {
	name := strings.TrimSpace(pruneTagName)
	if (strings.TrimSpace(pruneTagID) == "") == (name == "") {
		return fmt.Errorf("provide exactly one of --id or --name")
	}
	cfg, err := config.Load()
	if err != nil {
		return err
	}
	store := client.New(cfg.BaseURL(), cfg.Token)
	id := strings.TrimSpace(pruneTagID)
	if name != "" {
		tags, err := store.ListTags()
		if err != nil {
			return err
		}
		id, err = resolvePruneTagID(tags, name)
		if err != nil {
			return err
		}
	}
	report, err := tagcleanup.Prune(cmd.Context(), store, []string{id}, pruneTagApply)
	if err != nil {
		printJSON(report)
		return err
	}
	printJSON(report)
	return nil
}

func resolvePruneTagID(tags []client.Tag, name string) (string, error) {
	id := ""
	for _, tag := range tags {
		if tag.NestedName == name {
			if id != "" {
				return "", fmt.Errorf("tag name %q is ambiguous", name)
			}
			id = tag.ID
		}
	}
	if id == "" {
		return "", fmt.Errorf("tag %q does not exist", name)
	}
	return id, nil
}
