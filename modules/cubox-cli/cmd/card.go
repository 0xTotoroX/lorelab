package cmd

import (
	"fmt"
	"strings"

	"github.com/OLCUBO/cubox-cli/internal/client"
	"github.com/OLCUBO/cubox-cli/internal/config"
	"github.com/OLCUBO/cubox-cli/internal/timefmt"
	"github.com/spf13/cobra"
)

var (
	cardFolderFilter []string
	cardTagFilter    []string
	cardStarred      bool
	cardRead         bool
	cardUnread       bool
	cardAnnotated    bool
	cardArchived     bool
	cardLimit        int
	cardLastID       string
	cardAll          bool
	cardKeyword      string
	cardUrlFilter    string
	cardPage         int
	cardStartTime    string
	cardEndTime      string
	cardDetailID     string
)

var cardCmd = &cobra.Command{
	Use:   "card",
	Short: "Manage cards (bookmarks)",
}

var cardListCmd = &cobra.Command{
	Use:   "list",
	Short: "List and filter cards",
	Long: `Filter and list cards. Supports keyword search and exact URL lookup.

By default only non-archived cards are returned. Use --archived to
list archived cards instead.

When using --keyword or --url, pagination uses --page (1-based).
Otherwise, pagination uses --last-id (cursor-based).

Examples:
  cubox-cli card list
  cubox-cli card list --starred --limit 10
  cubox-cli card list --folder 7230156249357091393 --all
  cubox-cli card list --archived --limit 10
  cubox-cli card list --keyword "AI agent" --page 1
  cubox-cli card list --url "https://example.com/article"
  cubox-cli card list --start-time 2026-01-01
  cubox-cli card list --start-time 7d --end-time today`,
	RunE: runCardList,
}

var cardDetailCmd = &cobra.Command{
	Use:   "detail",
	Short: "Get full card detail with content, annotations, and AI insight",
	Long: `Retrieve the full detail of a card including article content (markdown),
annotations, and AI-generated insight (summary + Q&A).

Examples:
  cubox-cli card detail --id 7247925101516031380
  cubox-cli card detail --id 7247925101516031380 -o pretty`,
	RunE: runCardDetail,
}

var cardRagQuery string

var cardRagCmd = &cobra.Command{
	Use:   "rag",
	Short: "Semantic search cards via RAG query",
	Long: `Search cards using natural language via RAG (Retrieval-Augmented
Generation). Unlike keyword search (card list --keyword), RAG understands
intent and semantics, returning cards that are conceptually relevant even
when exact keywords don't match.

Use this for questions, conceptual queries, or topic exploration.
Use "card list --keyword" for exact or simple keyword matching.
Use "card list --url" to look up a card by its exact URL.

Examples:
  cubox-cli card rag --query "Java实现数据库图片上传功能"
  cubox-cli card rag --query "how to build a REST API with authentication"
  cubox-cli card rag --query "recent articles about large language models"`,
	RunE: runCardRag,
}

func init() {
	cardListCmd.Flags().StringSliceVar(&cardFolderFilter, "folder", nil, "filter by folder IDs (comma-separated)")
	cardListCmd.Flags().StringSliceVar(&cardTagFilter, "tag", nil, "filter by tag IDs (comma-separated, empty string = no tag)")
	cardListCmd.Flags().BoolVar(&cardStarred, "starred", false, "only starred cards")
	cardListCmd.Flags().BoolVar(&cardRead, "read", false, "only read cards")
	cardListCmd.Flags().BoolVar(&cardUnread, "unread", false, "only unread cards")
	cardListCmd.Flags().BoolVar(&cardAnnotated, "annotated", false, "only annotated cards")
	cardListCmd.Flags().BoolVar(&cardArchived, "archived", false, "only archived cards (default: only non-archived)")
	cardListCmd.Flags().IntVar(&cardLimit, "limit", 50, "page size")
	cardListCmd.Flags().StringVar(&cardLastID, "last-id", "", "last card ID for cursor pagination (non-search)")
	cardListCmd.Flags().BoolVar(&cardAll, "all", false, "auto-paginate to fetch all results")
	cardListCmd.Flags().StringVar(&cardKeyword, "keyword", "", "search keyword")
	cardListCmd.Flags().StringVar(&cardUrlFilter, "url", "", "filter by exact card URL")
	cardListCmd.Flags().IntVar(&cardPage, "page", 0, "page number for search pagination (1-based)")
	cardListCmd.Flags().StringVar(&cardStartTime, "start-time", "", "filter start time (today, yesterday, 7d, 2006-01-02, or full timestamp)")
	cardListCmd.Flags().StringVar(&cardEndTime, "end-time", "", "filter end time (today, yesterday, 7d, 2006-01-02, or full timestamp)")

	cardDetailCmd.Flags().StringVar(&cardDetailID, "id", "", "card ID (required)")
	cardDetailCmd.MarkFlagRequired("id")

	cardRagCmd.Flags().StringVar(&cardRagQuery, "query", "", "natural language query text (required)")
	cardRagCmd.MarkFlagRequired("query")

	cardCmd.AddCommand(cardListCmd, cardDetailCmd, cardRagCmd, cardStarCmd, cardReadCmd, cardMoveCmd, cardTagCmd)
	rootCmd.AddCommand(cardCmd)
}

// ---- batch card operations (web/app group) ----

var (
	batchIDs    []string
	starOn      bool
	starOff     bool
	moveTarget  string
	tagAddNames []string
	tagDelIDs   []string
)

var cardStarCmd = &cobra.Command{
	Use:   "star",
	Short: "Star/unstar cards in batch",
	Long: `Batch-star or batch-unstar cards. Provide exactly one of --on / --off.`,
	Example: `  cubox-cli card star --id 7435...,7436... --on`,
	RunE: func(cmd *cobra.Command, args []string) error {
		if len(batchIDs) == 0 {
			return fmt.Errorf("--id is required")
		}
		if starOn == starOff {
			return fmt.Errorf("provide exactly one of --on / --off")
		}
		cfg, err := config.Load()
		if err != nil {
			return err
		}
		web, err := webClient(cfg)
		if err != nil {
			return err
		}
		raw, err := web.WebCardsStar(batchIDs, starOn)
		if err != nil {
			return err
		}
		printJSON(map[string]interface{}{"count": len(batchIDs), "star": starOn, "data": jsonRaw(raw)})
		return nil
	},
}

var cardReadCmd = &cobra.Command{
	Use:   "read",
	Short: "Mark cards as read in batch",
	Example: `  cubox-cli card read --id 7435...,7436...`,
	RunE: func(cmd *cobra.Command, args []string) error {
		if len(batchIDs) == 0 {
			return fmt.Errorf("--id is required")
		}
		cfg, err := config.Load()
		if err != nil {
			return err
		}
		web, err := webClient(cfg)
		if err != nil {
			return err
		}
		raw, err := web.WebCardsRead(batchIDs)
		if err != nil {
			return err
		}
		printJSON(map[string]interface{}{"count": len(batchIDs), "message": "cards marked as read", "data": jsonRaw(raw)})
		return nil
	},
}

var cardMoveCmd = &cobra.Command{
	Use:   "move",
	Short: "Move cards to a folder in batch",
	Example: `  cubox-cli card move --id 7435...,7436... --folder-id 7230156249357091393`,
	RunE: func(cmd *cobra.Command, args []string) error {
		if len(batchIDs) == 0 {
			return fmt.Errorf("--id is required")
		}
		if moveTarget == "" {
			return fmt.Errorf("--folder-id is required")
		}
		cfg, err := config.Load()
		if err != nil {
			return err
		}
		web, err := webClient(cfg)
		if err != nil {
			return err
		}
		raw, err := web.WebCardsMove(batchIDs, moveTarget)
		if err != nil {
			return err
		}
		printJSON(map[string]interface{}{"count": len(batchIDs), "folder": moveTarget, "data": jsonRaw(raw)})
		return nil
	},
}

var cardTagCmd = &cobra.Command{
	Use:   "tag",
	Short: "Add tags (by name) to cards in batch",
	Long: `Batch-add tags by name to cards, optionally removing tag IDs.

Note: --add uses tag NAMES (created on the fly if missing, like the app);
--delete-tag-ids takes tag IDs.`,
	Example: `  cubox-cli card tag --id 7435...,7436... --add ai,llm --delete-tag-ids 7123...`,
	RunE: func(cmd *cobra.Command, args []string) error {
		if len(batchIDs) == 0 {
			return fmt.Errorf("--id is required")
		}
		if len(tagAddNames) == 0 && len(tagDelIDs) == 0 {
			return fmt.Errorf("provide --add and/or --delete-tag-ids")
		}
		cfg, err := config.Load()
		if err != nil {
			return err
		}
		web, err := webClient(cfg)
		if err != nil {
			return err
		}
		raw, err := web.WebCardsAddTagsByName(batchIDs, tagAddNames, tagDelIDs)
		if err != nil {
			return err
		}
		printJSON(map[string]interface{}{"count": len(batchIDs), "add": tagAddNames, "data": jsonRaw(raw)})
		return nil
	},
}

func init() {
	cardStarCmd.Flags().StringSliceVar(&batchIDs, "id", nil, "card IDs (comma-separated, required)")
	cardStarCmd.Flags().BoolVar(&starOn, "on", false, "star the cards")
	cardStarCmd.Flags().BoolVar(&starOff, "off", false, "unstar the cards")

	cardReadCmd.Flags().StringSliceVar(&batchIDs, "id", nil, "card IDs (comma-separated, required)")

	cardMoveCmd.Flags().StringSliceVar(&batchIDs, "id", nil, "card IDs (comma-separated, required)")
	cardMoveCmd.Flags().StringVar(&moveTarget, "folder-id", "", "destination folder ID (required)")

	cardTagCmd.Flags().StringSliceVar(&batchIDs, "id", nil, "card IDs (comma-separated, required)")
	cardTagCmd.Flags().StringSliceVar(&tagAddNames, "add", nil, "tag names to add (comma-separated)")
	cardTagCmd.Flags().StringSliceVar(&tagDelIDs, "delete-tag-ids", nil, "tag IDs to remove (comma-separated)")
}

func buildCardFilterRequest() (*client.CardFilterRequest, error) {
	startTime, err := timefmt.Parse(cardStartTime)
	if err != nil {
		return nil, fmt.Errorf("--start-time: %w", err)
	}
	endTime, err := timefmt.ParseEnd(cardEndTime)
	if err != nil {
		return nil, fmt.Errorf("--end-time: %w", err)
	}

	req := &client.CardFilterRequest{
		FolderFilters: cardFolderFilter,
		TagFilters:    cardTagFilter,
		Limit:         cardLimit,
		Keyword:       cardKeyword,
		UrlFilter:     cardUrlFilter,
		StartTime:     startTime,
		EndTime:       endTime,
	}

	if cardStarred {
		v := true
		req.Starred = &v
	}
	if cardRead {
		v := true
		req.Read = &v
	}
	if cardUnread {
		v := false
		req.Read = &v
	}
	if cardAnnotated {
		v := true
		req.Annotated = &v
	}
	if cardArchived {
		v := true
		req.Archived = &v
	}

	if isCardSearchMode() {
		if cardPage > 0 {
			req.Page = cardPage
		} else {
			req.Page = 1
		}
	} else {
		req.LastCardID = cardLastID
	}

	return req, nil
}

func isCardSearchMode() bool {
	return cardKeyword != "" || cardUrlFilter != ""
}

func runCardList(cmd *cobra.Command, args []string) error {
	cfg, err := config.Load()
	if err != nil {
		return err
	}
	c := client.New(cfg.BaseURL(), cfg.Token)

	req, err := buildCardFilterRequest()
	if err != nil {
		return err
	}

	if cardAll {
		return runCardListAll(c, req)
	}

	cards, err := c.FilterCards(req)
	if err != nil {
		return err
	}

	if outputFormat == "text" {
		printCardsText(cards)
		return nil
	}
	printJSON(cards)
	return nil
}

func runCardListAll(c *client.Client, req *client.CardFilterRequest) error {
	var allCards []client.Card

	if req.Keyword != "" || req.UrlFilter != "" {
		for page := 1; ; page++ {
			req.Page = page
			cards, err := c.FilterCards(req)
			if err != nil {
				return err
			}
			if len(cards) == 0 {
				break
			}
			allCards = append(allCards, cards...)
		}
	} else {
		for {
			cards, err := c.FilterCards(req)
			if err != nil {
				return err
			}
			if len(cards) == 0 {
				break
			}
			allCards = append(allCards, cards...)
			req.LastCardID = cards[len(cards)-1].ID
		}
	}

	if outputFormat == "text" {
		printCardsText(allCards)
		return nil
	}
	printJSON(allCards)
	return nil
}

func runCardDetail(cmd *cobra.Command, args []string) error {
	cfg, err := config.Load()
	if err != nil {
		return err
	}
	c := client.New(cfg.BaseURL(), cfg.Token)

	detail, err := c.GetCardDetail(cardDetailID)
	if err != nil {
		return err
	}

	if outputFormat == "text" {
		fmt.Print(detail.Content)
		return nil
	}
	printJSON(detail)
	return nil
}

func runCardRag(cmd *cobra.Command, args []string) error {
	cfg, err := config.Load()
	if err != nil {
		return err
	}
	c := client.New(cfg.BaseURL(), cfg.Token)

	cards, err := c.RagQueryCards(cardRagQuery)
	if err != nil {
		return err
	}

	if outputFormat == "text" {
		printCardsText(cards)
		return nil
	}
	printJSON(cards)
	return nil
}

func printCardsText(cards []client.Card) {
	for _, c := range cards {
		star := " "
		if c.Starred {
			star = "*"
		}
		readMark := " "
		if c.Read {
			readMark = "R"
		}
		tags := ""
		if len(c.Tags) > 0 {
			tags = " [" + strings.Join(c.Tags, ", ") + "]"
		}
		fmt.Printf("[%s%s] %s  %s%s\n", star, readMark, c.ID, c.Title, tags)
		if c.URL != "" {
			fmt.Printf("     %s\n", c.URL)
		}
		fmt.Println()
	}
}
