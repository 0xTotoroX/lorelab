package cmd

import (
	"fmt"

	"github.com/OLCUBO/cubox-cli/internal/config"
	"github.com/spf13/cobra"
)

var aiCmd = &cobra.Command{
	Use:   "ai",
	Short: "AI features",
	Long: `AI features via the web/app API group.

"ai generate" streams insight generation for a card (SSE). The stream is
printed to stdout as it arrives; generation consumes AI quota.
"ai ask" asks the Cubox AI assistant a question and streams the answer
(same quota). Pass --context to scope the question to a piece of text
(the app uses the card content for in-card Q&A).`,
}

var aiCard string

var aiGenerateCmd = &cobra.Command{
	Use:   "generate",
	Short: "Generate AI insight for a card (streams)",
	Example: `  cubox-cli ai generate --card 7247925101516031380`,
	RunE: func(cmd *cobra.Command, args []string) error {
		if aiCard == "" {
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
		return web.WebInsightGenerateStream(aiCard, func(line string) {
			fmt.Println(line)
		})
	},
}

var (
	askQuestion string
	askContext  string
	askCollect  string
)

var aiAskCmd = &cobra.Command{
	Use:   "ask",
	Short: "Ask the Cubox AI assistant a question (streams the answer)",
	Long: `Ask the Cubox AI assistant and stream the answer to stdout.

Consumes one AI Q&A quota per call (monthly quota; Pro+AI for higher limits).
--context scopes the question to the given text (the app passes the card
content for in-card Q&A).`,
	Example: `  cubox-cli ai ask --question "What did I save about Claude Code?"`,
	RunE: func(cmd *cobra.Command, args []string) error {
		if askQuestion == "" {
			return fmt.Errorf("--question is required")
		}
		cfg, err := config.Load()
		if err != nil {
			return err
		}
		web, err := webClient(cfg)
		if err != nil {
			return err
		}
		return web.WebAIAsk(askQuestion, askContext, askCollect, func(delta string) {
			fmt.Print(delta)
		})
	},
}

func init() {
	aiCmd.AddCommand(aiGenerateCmd)
	aiCmd.AddCommand(aiAskCmd)
	rootCmd.AddCommand(aiCmd)

	aiGenerateCmd.Flags().StringVar(&aiCard, "card", "", "card ID (required)")
	aiAskCmd.Flags().StringVar(&askQuestion, "question", "", "question text (required)")
	aiAskCmd.Flags().StringVar(&askContext, "context", "", "optional context text (e.g. card content)")
	aiAskCmd.Flags().StringVar(&askCollect, "collect-id", "", "optional collection box ID (assistant panel mode)")
}
