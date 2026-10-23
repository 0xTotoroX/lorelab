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
	saveFolder      string
	saveTags        []string
	saveTitle       string
	saveDesc        string
	saveJSON        string
	saveSkipExist   bool
	saveVerify      bool
)

// saveBatchSize is the server-side batch cap: the /c/api/cli/cards/save
// endpoint silently truncates larger batches (verified live). Keep every
// request at or below this.
const saveBatchSize = 20

var saveCmd = &cobra.Command{
	Use:   "save [urls...]",
	Short: "Save web pages as bookmarks",
	Long: `Save one or more web pages to your Cubox collection.

Three input modes:

1. URL arguments (simple — just URLs):
   cubox-cli save https://example.com https://another.com

2. Single card with metadata:
   cubox-cli save https://example.com --title "Example" --desc "A description"

3. Batch via JSON (full control):
   cubox-cli save --json '[{"url":"https://a.com","title":"A"},{"url":"https://b.com"}]'

All modes support --folder and --tag flags. Folders and tags are
specified by name (including nested paths like "parent/child"),
not by ID.

Examples:
  cubox-cli save https://example.com
  cubox-cli save https://a.com https://b.com --folder "Reading List"
  cubox-cli save https://example.com --title "My Page" --desc "Interesting read"
  cubox-cli save --json '[{"url":"https://a.com","title":"Title A"}]' --tag tech,AI/LLM`,
	RunE: runSave,
}

func init() {
	saveCmd.Flags().StringVar(&saveFolder, "folder", "", "target folder name (e.g. \"Reading List\" or \"parent/child\")")
	saveCmd.Flags().StringSliceVar(&saveTags, "tag", nil, "tag names (comma-separated, supports nested like \"parent/child\")")
	saveCmd.Flags().StringVar(&saveTitle, "title", "", "title for the saved page (single URL mode)")
	saveCmd.Flags().StringVar(&saveDesc, "desc", "", "description for the saved page (single URL mode)")
	saveCmd.Flags().StringVar(&saveJSON, "json", "", `batch card entries as JSON array: [{"url":"...","title":"...","description":"..."}]`)
	saveCmd.Flags().BoolVar(&saveSkipExist, "skip-existing", false, "skip URLs that are already saved (full-library URL diff before saving)")
	saveCmd.Flags().BoolVar(&saveVerify, "verify", false, "after saving, audit every URL to confirm it actually landed (slower)")

	rootCmd.AddCommand(saveCmd)
}

func runSave(cmd *cobra.Command, args []string) error {
	cards, err := buildSaveCards(args)
	if err != nil {
		return err
	}

	cfg, err := config.Load()
	if err != nil {
		return err
	}
	c := client.New(cfg.BaseURL(), cfg.Token)

	if saveSkipExist {
		var skipped int
		cards, skipped, err = filterExisting(c, cards)
		if err != nil {
			return err
		}
		fmt.Printf("Skipping %d already-saved card(s); %d to save.\n", skipped, len(cards))
		if len(cards) == 0 {
			fmt.Println("Nothing to save.")
			return nil
		}
	}

	req := &client.SaveCardsRequest{
		Cards:          cards,
		TagNestedNames: saveTags,
	}

	// Nested --folder support: the server treats "a/b" as a flat folder name
	// containing a slash. Resolve the path level by level (creating missing
	// folders), save without a folder, then move the saved cards into the
	// deepest folder. For large batches prefer `cubox-cli import bookmarks`.
	nestedTarget := ""
	if saveFolder != "" && strings.Contains(saveFolder, "/") {
		web, err := webClient(cfg)
		if err != nil {
			return err
		}
		nestedTarget, err = ensureFolderPath(web, saveFolder)
		if err != nil {
			return err
		}
	} else {
		req.FolderNestedName = saveFolder
	}

	// Batched save: the server truncates >20-entry batches silently.
	saved := 0
	for i := 0; i < len(cards); i += saveBatchSize {
		end := i + saveBatchSize
		if end > len(cards) {
			end = len(cards)
		}
		req.Cards = cards[i:end]
		if _, err := c.SaveCards(req); err != nil {
			return fmt.Errorf("batch %d-%d failed: %w — stopping; %d/%d card(s) saved before failure", i+1, end, err, saved, len(cards))
		}
		saved += end - i
		if len(cards) > saveBatchSize {
			fmt.Printf("  batch done: %d/%d saved\n", saved, len(cards))
		}
	}

	if saveVerify && nestedTarget == "" {
		// URL-level audit: confirm every card actually landed.
		missing := 0
		for _, card := range cards {
			found, err := c.FilterCards(&client.CardFilterRequest{UrlFilter: card.URL, Limit: 1})
			if err != nil || len(found) == 0 {
				missing++
				fmt.Printf("  WARNING unresolved: %s\n", card.URL)
			}
		}
		if missing > 0 {
			fmt.Printf("Saved %d card(s); %d UNRESOLVED after verify (parsing may be async — re-run with --skip-existing to retry).\n", saved, missing)
		} else {
			fmt.Printf("Saved %d card(s); verify passed — all %d URLs resolved.\n", saved, len(cards))
		}
		return nil
	}

	if nestedTarget == "" {
		fmt.Printf("Saved %d card(s) successfully.\n", len(cards))
		return nil
	}

	// Resolve each saved card by its URL and move it into the target folder.
	web, err := webClient(cfg)
	if err != nil {
		return err
	}
	moved, unresolved := 0, []string{}
	for _, card := range cards {
		found, err := c.FilterCards(&client.CardFilterRequest{UrlFilter: card.URL, Limit: 1})
		if err != nil || len(found) == 0 {
			unresolved = append(unresolved, card.URL)
			continue
		}
		if _, err := web.WebCardsMove([]string{found[0].ID}, nestedTarget); err != nil {
			unresolved = append(unresolved, card.URL)
			continue
		}
		moved++
	}
	fmt.Printf("Saved %d card(s) successfully; moved %d into %q.\n", saved, moved, saveFolder)
	if len(unresolved) > 0 {
		fmt.Printf("WARNING: %d card(s) could not be resolved/moved yet (parsing is async) — re-run the same command with --skip-existing to retry, or move them manually.\n", len(unresolved))
		for _, u := range unresolved {
			fmt.Printf("  unresolved: %s\n", u)
		}
	}
	return nil
}

func buildSaveCards(args []string) ([]client.SaveCardEntry, error) {
	hasJSON := saveJSON != ""
	hasArgs := len(args) > 0
	hasMeta := saveTitle != "" || saveDesc != ""

	if hasJSON && hasArgs {
		return nil, fmt.Errorf("cannot use both --json and URL arguments")
	}
	if hasJSON && hasMeta {
		return nil, fmt.Errorf("cannot use --title/--desc with --json")
	}
	if !hasJSON && !hasArgs {
		return nil, fmt.Errorf("provide URLs as arguments, or use --json for batch input")
	}

	if hasJSON {
		var cards []client.SaveCardEntry
		if err := json.Unmarshal([]byte(saveJSON), &cards); err != nil {
			return nil, fmt.Errorf("invalid --json: %w", err)
		}
		for i, c := range cards {
			if c.URL == "" {
				return nil, fmt.Errorf("--json entry %d: url is required", i)
			}
		}
		return cards, nil
	}

	if hasMeta && len(args) > 1 {
		return nil, fmt.Errorf("--title/--desc apply to a single URL; pass one URL or use --json for batch")
	}

	cards := make([]client.SaveCardEntry, 0, len(args))
	for _, u := range args {
		cards = append(cards, client.SaveCardEntry{
			URL:         u,
			Title:       saveTitle,
			Description: saveDesc,
		})
	}
	return cards, nil
}

// filterExisting removes entries whose URL is already saved. It pages through
// the whole library once (cursor pagination) and builds a URL set locally —
// the server has no batch URL lookup and no dedup of its own.
func filterExisting(c *client.Client, cards []client.SaveCardEntry) ([]client.SaveCardEntry, int, error) {
	seen := map[string]bool{}
	last := ""
	for {
		found, err := c.FilterCards(&client.CardFilterRequest{Limit: 50, LastCardID: last})
		if err != nil {
			return nil, 0, fmt.Errorf("listing library for --skip-existing: %w", err)
		}
		if len(found) == 0 {
			break
		}
		for _, fc := range found {
			seen[fc.URL] = true
			last = fc.ID
		}
		if len(found) < 50 {
			break
		}
	}
	kept := make([]client.SaveCardEntry, 0, len(cards))
	skipped := 0
	for _, card := range cards {
		if seen[card.URL] {
			skipped++
			continue
		}
		kept = append(kept, card)
	}
	return kept, skipped, nil
}
