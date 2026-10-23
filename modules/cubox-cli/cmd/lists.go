package cmd

import (
	"fmt"

	"github.com/OLCUBO/cubox-cli/internal/config"
	"github.com/spf13/cobra"
)

var listsCmd = &cobra.Command{
	Use:   "lists",
	Short: "Manage reading lists",
	Long: `Manage reading lists — curated, shareable collections of cards.

Note: creating/deleting reading lists themselves is available in the app;
this command group covers listing them and adding/removing cards.`,
}

var listsListCmd = &cobra.Command{
	Use:   "list",
	Short: "List your reading lists",
	RunE: func(cmd *cobra.Command, args []string) error {
		cfg, err := config.Load()
		if err != nil {
			return err
		}
		web, err := webClient(cfg)
		if err != nil {
			return err
		}
		raw, err := web.WebReadingLists()
		if err != nil {
			return err
		}
		printJSON(jsonRaw(raw))
		return nil
	},
}

var (
	addListID  string
	addCardID  string
	addHl      bool
	addNote    bool
	rmListID   string
	rmCardID   string
)

var listsAddItemCmd = &cobra.Command{
	Use:   "add-item",
	Short: "Add a card to a reading list",
	Example: `  cubox-cli lists add-item --list 7123... --card 7456... --highlight --note`,
	RunE: func(cmd *cobra.Command, args []string) error {
		if addListID == "" || addCardID == "" {
			return fmt.Errorf("--list and --card are required")
		}
		cfg, err := config.Load()
		if err != nil {
			return err
		}
		web, err := webClient(cfg)
		if err != nil {
			return err
		}
		raw, err := web.WebReadingListAddItem(addListID, addCardID, addHl, addNote)
		if err != nil {
			return err
		}
		printJSON(map[string]interface{}{"message": "card added to reading list", "data": jsonRaw(raw)})
		return nil
	},
}

var listsRemoveItemCmd = &cobra.Command{
	Use:   "remove-item",
	Short: "Remove a card from a reading list",
	Example: `  cubox-cli lists remove-item --list 7123... --card 7456...`,
	RunE: func(cmd *cobra.Command, args []string) error {
		if rmListID == "" || rmCardID == "" {
			return fmt.Errorf("--list and --card are required")
		}
		cfg, err := config.Load()
		if err != nil {
			return err
		}
		web, err := webClient(cfg)
		if err != nil {
			return err
		}
		raw, err := web.WebReadingListRemoveItem(rmListID, rmCardID)
		if err != nil {
			return err
		}
		printJSON(map[string]interface{}{"message": "card removed from reading list", "data": jsonRaw(raw)})
		return nil
	},
}

var (
	newTitle string
	newIntro string
	delList  string
)

var listsNewCmd = &cobra.Command{
	Use:   "new",
	Short: "Create a reading list",
	Example: `  cubox-cli lists new --title "AI Weekly" --intro "Curated picks"`,
	RunE: func(cmd *cobra.Command, args []string) error {
		if newTitle == "" {
			return fmt.Errorf("--title is required")
		}
		cfg, err := config.Load()
		if err != nil {
			return err
		}
		web, err := webClient(cfg)
		if err != nil {
			return err
		}
		raw, err := web.WebReadingListCreate(newTitle, newIntro)
		if err != nil {
			return err
		}
		printJSON(map[string]interface{}{"message": "reading list created", "title": newTitle, "data": jsonRaw(raw)})
		return nil
	},
}

var listsDeleteCmd = &cobra.Command{
	Use:   "delete",
	Short: "Delete a reading list",
	Example: `  cubox-cli lists delete --list 7123...`,
	RunE: func(cmd *cobra.Command, args []string) error {
		if delList == "" {
			return fmt.Errorf("--list is required")
		}
		cfg, err := config.Load()
		if err != nil {
			return err
		}
		web, err := webClient(cfg)
		if err != nil {
			return err
		}
		raw, err := web.WebReadingListDelete(delList)
		if err != nil {
			return err
		}
		printJSON(map[string]interface{}{"message": "reading list deleted", "data": jsonRaw(raw)})
		return nil
	},
}

// ---- extra reading-list operations ----

var (
	updListID string
	updTitle  string
	updIntro  string
	pubListID string
	pubOn     bool
	pubOff    bool
	colListID string
	colCardID string
	clAllID   string
	sortList  string
	sortIDs   []string
	checkIDs  []string
	listPage  int
	listSize  int
)

var listsUpdateCmd = &cobra.Command{
	Use:   "update",
	Short: "Update a reading list title/intro",
	RunE: func(cmd *cobra.Command, args []string) error {
		if updListID == "" || (updTitle == "" && updIntro == "") {
			return fmt.Errorf("--list and at least one of --title/--intro are required")
		}
		cfg, err := config.Load()
		if err != nil {
			return err
		}
		web, err := webClient(cfg)
		if err != nil {
			return err
		}
		raw, err := web.WebReadingListUpdate(updListID, updTitle, updIntro)
		if err != nil {
			return err
		}
		printJSON(map[string]interface{}{"message": "reading list updated", "data": jsonRaw(raw)})
		return nil
	},
}

var listsPublishCmd = &cobra.Command{
	Use:   "publish",
	Short: "Publish/unpublish a reading list",
	RunE: func(cmd *cobra.Command, args []string) error {
		if pubListID == "" || (pubOn == pubOff) {
			return fmt.Errorf("--list and exactly one of --on/--off are required")
		}
		cfg, err := config.Load()
		if err != nil {
			return err
		}
		web, err := webClient(cfg)
		if err != nil {
			return err
		}
		raw, err := web.WebReadingListPublish(pubListID, pubOn)
		if err != nil {
			return err
		}
		printJSON(map[string]interface{}{"message": map[bool]string{true: "published", false: "unpublished"}[pubOn], "data": jsonRaw(raw)})
		return nil
	},
}

var listsCollectCmd = &cobra.Command{
	Use:   "collect",
	Short: "Collect a card into a reading list",
	RunE: func(cmd *cobra.Command, args []string) error {
		if colListID == "" || colCardID == "" {
			return fmt.Errorf("--list and --card are required")
		}
		cfg, err := config.Load()
		if err != nil {
			return err
		}
		web, err := webClient(cfg)
		if err != nil {
			return err
		}
		raw, err := web.WebReadingListCollect(colListID, colCardID)
		if err != nil {
			return err
		}
		printJSON(map[string]interface{}{"message": "card collected", "data": jsonRaw(raw)})
		return nil
	},
}

var listsCollectAllCmd = &cobra.Command{
	Use:   "collect-all",
	Short: "Trigger collecting the full list content",
	RunE: func(cmd *cobra.Command, args []string) error {
		if clAllID == "" {
			return fmt.Errorf("--list is required")
		}
		cfg, err := config.Load()
		if err != nil {
			return err
		}
		web, err := webClient(cfg)
		if err != nil {
			return err
		}
		raw, err := web.WebReadingListCollectAll(clAllID)
		if err != nil {
			return err
		}
		printJSON(map[string]interface{}{"message": "collect-all triggered", "data": jsonRaw(raw)})
		return nil
	},
}

var listsCardsCmd = &cobra.Command{
	Use:   "cards",
	Short: "List the cards inside a reading list",
	RunE: func(cmd *cobra.Command, args []string) error {
		if sortList == "" {
			return fmt.Errorf("--list is required")
		}
		cfg, err := config.Load()
		if err != nil {
			return err
		}
		web, err := webClient(cfg)
		if err != nil {
			return err
		}
		raw, err := web.WebReadingListCards(sortList, listPage, listSize)
		if err != nil {
			return err
		}
		printJSON(jsonRaw(raw))
		return nil
	},
}

var listsSortCmd = &cobra.Command{
	Use:   "sort",
	Short: "Reorder the cards of a reading list",
	RunE: func(cmd *cobra.Command, args []string) error {
		if sortList == "" || len(sortIDs) == 0 {
			return fmt.Errorf("--list and --card are required (full ordered card ID list)")
		}
		cfg, err := config.Load()
		if err != nil {
			return err
		}
		web, err := webClient(cfg)
		if err != nil {
			return err
		}
		raw, err := web.WebListsItemsSort(sortList, sortIDs)
		if err != nil {
			return err
		}
		printJSON(map[string]interface{}{"message": "items sorted", "data": jsonRaw(raw)})
		return nil
	},
}

var listsCheckCmd = &cobra.Command{
	Use:   "check",
	Short: "Report which reading lists contain the given cards",
	RunE: func(cmd *cobra.Command, args []string) error {
		if len(checkIDs) == 0 {
			return fmt.Errorf("--card is required")
		}
		cfg, err := config.Load()
		if err != nil {
			return err
		}
		web, err := webClient(cfg)
		if err != nil {
			return err
		}
		raw, err := web.WebListsCheck(checkIDs)
		if err != nil {
			return err
		}
		printJSON(jsonRaw(raw))
		return nil
	},
}

func init() {
	listsCmd.AddCommand(listsListCmd)
	listsCmd.AddCommand(listsNewCmd)
	listsCmd.AddCommand(listsDeleteCmd)
	listsCmd.AddCommand(listsUpdateCmd)
	listsCmd.AddCommand(listsPublishCmd)
	listsCmd.AddCommand(listsAddItemCmd)
	listsCmd.AddCommand(listsRemoveItemCmd)
	listsCmd.AddCommand(listsCollectCmd)
	listsCmd.AddCommand(listsCollectAllCmd)
	listsCmd.AddCommand(listsCardsCmd)
	listsCmd.AddCommand(listsSortCmd)
	listsCmd.AddCommand(listsCheckCmd)
	rootCmd.AddCommand(listsCmd)

	listsNewCmd.Flags().StringVar(&newTitle, "title", "", "reading list title (required)")
	listsNewCmd.Flags().StringVar(&newIntro, "intro", "", "reading list intro (optional)")
	listsDeleteCmd.Flags().StringVar(&delList, "list", "", "reading list ID (required)")
	listsUpdateCmd.Flags().StringVar(&updListID, "list", "", "reading list ID (required)")
	listsUpdateCmd.Flags().StringVar(&updTitle, "title", "", "new title")
	listsUpdateCmd.Flags().StringVar(&updIntro, "intro", "", "new intro")
	listsPublishCmd.Flags().StringVar(&pubListID, "list", "", "reading list ID (required)")
	listsPublishCmd.Flags().BoolVar(&pubOn, "on", false, "publish")
	listsPublishCmd.Flags().BoolVar(&pubOff, "off", false, "unpublish")
	listsAddItemCmd.Flags().StringVar(&addListID, "list", "", "reading list ID (required)")
	listsAddItemCmd.Flags().StringVar(&addCardID, "card", "", "card ID (required)")
	listsAddItemCmd.Flags().BoolVar(&addHl, "highlight", false, "include highlights")
	listsAddItemCmd.Flags().BoolVar(&addNote, "note", false, "include notes")
	listsRemoveItemCmd.Flags().StringVar(&rmListID, "list", "", "reading list ID (required)")
	listsRemoveItemCmd.Flags().StringVar(&rmCardID, "card", "", "card ID (required)")
	listsCollectCmd.Flags().StringVar(&colListID, "list", "", "reading list ID (required)")
	listsCollectCmd.Flags().StringVar(&colCardID, "card", "", "card ID (required)")
	listsCollectAllCmd.Flags().StringVar(&clAllID, "list", "", "reading list ID (required)")
	listsCardsCmd.Flags().StringVar(&sortList, "list", "", "reading list ID (required)")
	listsCardsCmd.Flags().IntVar(&listPage, "page", 1, "page number (1-based)")
	listsCardsCmd.Flags().IntVar(&listSize, "size", 20, "page size")
	listsSortCmd.Flags().StringVar(&sortList, "list", "", "reading list ID (required)")
	listsSortCmd.Flags().StringSliceVar(&sortIDs, "card", nil, "full ordered card ID list (required)")
	listsCheckCmd.Flags().StringSliceVar(&checkIDs, "card", nil, "card IDs (comma-separated, required)")
}
