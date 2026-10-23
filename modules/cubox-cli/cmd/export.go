package cmd

import (
	"fmt"

	"github.com/OLCUBO/cubox-cli/internal/config"
	"github.com/spf13/cobra"
)

var exportCmd = &cobra.Command{
	Use:   "export",
	Short: "Export your library",
	Long: `Export bookmarks via the web/app API group.

"export status" shows today's export count and account info;
"export bookmarks" requests a full-library export (the server responds with
the export task payload; large libraries are processed asynchronously).`,
}

var exportStatusCmd = &cobra.Command{
	Use:   "status",
	Short: "Show export-related counters",
	RunE: func(cmd *cobra.Command, args []string) error {
		cfg, err := config.Load()
		if err != nil {
			return err
		}
		web, err := webClient(cfg)
		if err != nil {
			return err
		}
		out := map[string]interface{}{}
		if raw, err := web.WebGetRaw("/c/api/bookmark/export/today/count"); err == nil {
			out["todayCount"] = jsonRaw(raw)
		} else {
			out["todayCount_error"] = err.Error()
		}
		if raw, err := web.WebGetRaw("/c/api/import/ready"); err == nil {
			out["importReady"] = jsonRaw(raw)
		}
		printJSON(out)
		return nil
	},
}

var exportBookmarksCmd = &cobra.Command{
	Use:   "bookmarks",
	Short: "Request a full-library bookmark export",
	RunE: func(cmd *cobra.Command, args []string) error {
		cfg, err := config.Load()
		if err != nil {
			return err
		}
		web, err := webClient(cfg)
		if err != nil {
			return err
		}
		raw, err := web.WebGetRaw("/c/api/v3/bookmark/export")
		if err != nil {
			return err
		}
		printJSON(map[string]interface{}{
			"message": "export requested — see data for the task/URL payload",
			"data":    jsonRaw(raw),
		})
		return nil
	},
}

var (
	mailIDs  []string
	mailAddr string
)

var exportMailCmd = &cobra.Command{
	Use:   "mail",
	Short: "Export selected cards by email (async)",
	Long: `Request an async export of the given cards; Cubox emails the export
file to the address you provide.`,
	Example: `  cubox-cli export mail --email me@example.com --card 7435...,7436...`,
	RunE: func(cmd *cobra.Command, args []string) error {
		if len(mailIDs) == 0 {
			return fmt.Errorf("--card is required")
		}
		if mailAddr == "" {
			return fmt.Errorf("--email is required")
		}
		cfg, err := config.Load()
		if err != nil {
			return err
		}
		web, err := webClient(cfg)
		if err != nil {
			return err
		}
		raw, err := web.WebCardsExportMail(mailIDs, mailAddr)
		if err != nil {
			return err
		}
		printJSON(map[string]interface{}{
			"message": fmt.Sprintf("export of %d card(s) requested — check your inbox at %s", len(mailIDs), mailAddr),
			"data":    jsonRaw(raw),
		})
		return nil
	},
}

func init() {
	exportCmd.AddCommand(exportStatusCmd)
	exportCmd.AddCommand(exportBookmarksCmd)
	exportCmd.AddCommand(exportMailCmd)
	rootCmd.AddCommand(exportCmd)

	exportMailCmd.Flags().StringSliceVar(&mailIDs, "card", nil, "card IDs to export (comma-separated, required)")
	exportMailCmd.Flags().StringVar(&mailAddr, "email", "", "email address to receive the export (required)")
}

var _ = fmt.Sprintf
