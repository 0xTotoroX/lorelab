package cmd

import (
	"context"
	"fmt"
	"os"
	"strings"

	"github.com/OLCUBO/cubox-cli/internal/client"
	"github.com/OLCUBO/cubox-cli/internal/config"
	"github.com/OLCUBO/cubox-cli/internal/tagcleanup"
	"github.com/spf13/cobra"
)

const detailPreviewThreshold = 3

var (
	deleteIDs     []string
	deleteDryRun  bool
	keepEmptyTags bool
)

var deleteCmd = &cobra.Command{
	Use:   "delete",
	Short: "Delete cards",
	Long: `Delete one or more cards by ID.

Use --dry-run to preview which cards would be deleted without actually
removing them. This is especially recommended when scripting or when
an AI Agent is performing deletions on behalf of a user.

When deleting up to 3 cards, the CLI shows titles and URLs in the preview.
For larger batches, it shows only the card count and predicted empty tags.

After a successful deletion, the CLI checks tags that were on those cards.
Empty leaf tags with no active or archived cards are deleted automatically.
Use --keep-empty-tags to leave them in place. For an already-empty tag, use
"cubox-cli tag prune-empty --name NAME" to preview it.

Examples:
  cubox-cli delete --id 7435692934957108160
  cubox-cli delete --id 7435692934957108160,7435691601617225646
  cubox-cli delete --id 7435692934957108160 --dry-run`,
	RunE: runDelete,
}

func init() {
	deleteCmd.Flags().StringSliceVar(&deleteIDs, "id", nil, "card IDs to delete (comma-separated, required)")
	deleteCmd.MarkFlagRequired("id")
	deleteCmd.Flags().BoolVar(&deleteDryRun, "dry-run", false, "preview cards to be deleted without actually deleting")
	deleteCmd.Flags().BoolVar(&keepEmptyTags, "keep-empty-tags", false, "skip automatic cleanup of empty tags after deleting cards")

	rootCmd.AddCommand(deleteCmd)
}

type deletePreview struct {
	ID    string `json:"id"`
	Title string `json:"title,omitempty"`
	URL   string `json:"url,omitempty"`
}

type deleteResult struct {
	DryRun  bool               `json:"dry_run"`
	Count   int                `json:"count"`
	Cards   []deletePreview    `json:"cards,omitempty"`
	Tags    *tagcleanup.Report `json:"tag_cleanup,omitempty"`
	Message string             `json:"message"`
}

func runDelete(cmd *cobra.Command, args []string) error {
	// pflag keeps trailing-comma artifacts as empty strings — drop them so
	// counts and server payloads stay accurate.
	cleaned := make([]string, 0, len(deleteIDs))
	for _, id := range deleteIDs {
		if id = strings.TrimSpace(id); id != "" {
			cleaned = append(cleaned, id)
		}
	}
	deleteIDs = cleaned
	if len(deleteIDs) == 0 {
		return fmt.Errorf("at least one card ID is required")
	}

	cfg, err := config.Load()
	if err != nil {
		return err
	}
	c := client.New(cfg.BaseURL(), cfg.Token)

	if deleteDryRun {
		return outputDryRun(cmd.Context(), c, deleteIDs, keepEmptyTags)
	}
	return executeDelete(cmd.Context(), c, deleteIDs, keepEmptyTags)
}

func outputDryRun(ctx context.Context, c *client.Client, ids []string, keepTags bool) error {
	count := len(ids)
	result := deleteResult{
		DryRun:  true,
		Count:   count,
		Message: fmt.Sprintf("[dry-run] Would delete %d card(s). No changes were made.", count),
	}
	if count <= detailPreviewThreshold {
		result.Cards = fetchDeletePreviews(c, ids)
	}
	if !keepTags {
		tags, err := c.ListTags()
		if err != nil {
			return err
		}
		affected, err := tagcleanup.AffectedTags(c, tags, ids)
		if err != nil {
			return err
		}
		preview, err := tagcleanup.PreviewAfterDelete(ctx, c, tags, affected, ids)
		if err != nil {
			return err
		}
		result.Tags = &preview
	}
	if outputFormat == "text" {
		fmt.Fprintf(os.Stderr, "[dry-run] Would delete %d card(s):\n\n", count)
		if len(result.Cards) > 0 {
			printDeletePreviewText(result.Cards)
		}
		if result.Tags != nil {
			fmt.Fprintf(os.Stderr, "Tags that would become empty: %v\n", result.Tags.Eligible)
		}
		fmt.Fprintln(os.Stderr, "No changes were made. Remove --dry-run to delete.")
		return nil
	}
	printJSON(result)
	return nil
}

func executeDelete(ctx context.Context, c *client.Client, ids []string, keepTags bool) error {
	count := len(ids)

	if outputFormat == "text" && count <= detailPreviewThreshold {
		previews := fetchDeletePreviews(c, ids)
		fmt.Fprintf(os.Stderr, "Deleting %d card(s):\n\n", count)
		printDeletePreviewText(previews)
	}

	workflow, err := deleteCardsAndPrune(ctx, c, ids, keepTags)
	if !workflow.CardDeleted {
		return err
	}

	result := deleteResult{
		DryRun:  false,
		Count:   count,
		Message: fmt.Sprintf("Successfully deleted %d card(s).", count),
	}
	if !keepTags {
		result.Tags = &workflow.Tags
	}
	if err != nil {
		result.Message = fmt.Sprintf("Deleted %d card(s), but empty-tag cleanup failed: %v", count, err)
	}

	if outputFormat == "text" {
		fmt.Fprintln(os.Stderr, result.Message)
		if result.Tags != nil {
			fmt.Fprintf(os.Stderr, "Empty tags deleted: %v; skipped: %v\n", result.Tags.Deleted, result.Tags.Skipped)
		}
		return err
	}
	printJSON(result)
	return err
}

type deleteStore interface {
	tagcleanup.Store
	tagcleanup.CardReader
	DeleteCards([]string) error
}

type deleteWorkflowReport struct {
	CardDeleted bool
	Tags        tagcleanup.Report
}

func deleteCardsAndPrune(ctx context.Context, store deleteStore, ids []string, keepTags bool) (deleteWorkflowReport, error) {
	report := deleteWorkflowReport{}
	var affected []string
	if !keepTags {
		tags, err := store.ListTags()
		if err != nil {
			return report, err
		}
		affected, err = tagcleanup.AffectedTags(store, tags, ids)
		if err != nil {
			return report, err
		}
	}
	if err := ctx.Err(); err != nil {
		return report, err
	}
	if err := store.DeleteCards(ids); err != nil {
		return report, err
	}
	report.CardDeleted = true
	if !keepTags {
		var err error
		report.Tags, err = tagcleanup.Prune(ctx, store, affected, true)
		if err != nil {
			return report, fmt.Errorf("cards were deleted; empty-tag cleanup: %w", err)
		}
	}
	return report, nil
}

// fetchDeletePreviews fetches card details for a small set of IDs to build a
// human-readable preview. Only called when len(ids) <= detailPreviewThreshold.
// Failures are tolerated — the card is still listed with its ID only.
func fetchDeletePreviews(c *client.Client, ids []string) []deletePreview {
	previews := make([]deletePreview, 0, len(ids))
	for _, id := range ids {
		p := deletePreview{ID: id}
		if detail, err := c.GetCardDetail(id); err == nil {
			p.Title = detail.Title
			p.URL = detail.URL
		}
		previews = append(previews, p)
	}
	return previews
}

func printDeletePreviewText(previews []deletePreview) {
	for _, p := range previews {
		title := p.Title
		if title == "" {
			title = "(unknown)"
		}
		fmt.Fprintf(os.Stderr, "  - %s  %s\n", p.ID, title)
		if p.URL != "" {
			fmt.Fprintf(os.Stderr, "    %s\n", p.URL)
		}
	}
	fmt.Fprintln(os.Stderr)
}
