package cmd

import (
	"encoding/json"
	"fmt"
	"strings"

	"github.com/OLCUBO/cubox-cli/internal/client"
	"github.com/OLCUBO/cubox-cli/internal/config"
	"github.com/spf13/cobra"
)

var recycleCmd = &cobra.Command{
	Use:   "recycle",
	Short: "Manage the recycle bin",
	Long: `Manage deleted cards in the recycle bin.

Deleted cards stay in the recycle bin before permanent removal. Use
"recycle list" to inspect it, "recycle recover" to restore cards, and
"recycle clean" to permanently remove cards (destructive).`,
}

var recyclePage int

var recycleListCmd = &cobra.Command{
	Use:   "list",
	Short: "List cards in the recycle bin",
	RunE: func(cmd *cobra.Command, args []string) error {
		cfg, err := config.Load()
		if err != nil {
			return err
		}
		web, err := webClient(cfg)
		if err != nil {
			return err
		}
		raw, err := web.WebRecycleList(recyclePage)
		if err != nil {
			return err
		}
		printJSON(jsonRaw(raw))
		return nil
	},
}

var (
	recoverIDs []string
	cleanIDs   []string
)

var recycleRecoverCmd = &cobra.Command{
	Use:   "recover",
	Short: "Restore cards from the recycle bin",
	Example: `  cubox-cli recycle recover --id 7435692934957108160,7435691601617225646`,
	RunE: func(cmd *cobra.Command, args []string) error {
		if len(recoverIDs) == 0 {
			return fmt.Errorf("--id is required")
		}
		return runRecycleWrite(recoverIDs, false)
	},
}

var recycleCleanCmd = &cobra.Command{
	Use:   "clean",
	Short: "Permanently remove cards from the recycle bin (destructive)",
	Example: `  cubox-cli recycle clean --id 7435692934957108160`,
	RunE: func(cmd *cobra.Command, args []string) error {
		if len(cleanIDs) == 0 {
			return fmt.Errorf("--id is required")
		}
		return runRecycleWrite(cleanIDs, true)
	},
}

func runRecycleWrite(ids []string, permanent bool) error {
	cfg, err := config.Load()
	if err != nil {
		return err
	}
	web, err := webClient(cfg)
	if err != nil {
		return err
	}
	var raw json.RawMessage
	if permanent {
		raw, err = web.WebRecycleClean(ids)
	} else {
		raw, err = web.WebRecycleRecover(ids)
	}
	if err != nil {
		return err
	}
	action := "recovered"
	if permanent {
		action = "permanently removed"
	}
	printJSON(map[string]interface{}{
		"count":   len(ids),
		"ids":     strings.Join(ids, ","),
		"message": fmt.Sprintf("%d card(s) %s", len(ids), action),
		"data":    raw,
	})
	return nil
}

func init() {
	recycleCmd.AddCommand(recycleListCmd)
	recycleCmd.AddCommand(recycleRecoverCmd)
	recycleCmd.AddCommand(recycleCleanCmd)
	rootCmd.AddCommand(recycleCmd)

	recycleListCmd.Flags().IntVar(&recyclePage, "page", 1, "page number (1-based)")
	recycleRecoverCmd.Flags().StringSliceVar(&recoverIDs, "id", nil, "card IDs to restore (comma-separated, required)")
	recycleCleanCmd.Flags().StringSliceVar(&cleanIDs, "id", nil, "card IDs to permanently remove (comma-separated, required)")
}

// jsonRaw adapts json.RawMessage for printJSON.
type jsonRaw json.RawMessage

func (r jsonRaw) MarshalJSON() ([]byte, error) {
	if len(r) == 0 {
		return []byte("null"), nil
	}
	return r, nil
}

var _ = client.APIResponse{} // keep import stable if unused in future edits
