// [INPUT]: CardDetail and Goldmark's CommonMark syntax tree.
// [OUTPUT]: ClassifyCardContent, a conservative body/description/link/empty hint.
// [POS]: Batch content evidence only; never proves completeness or fetches URLs.
// [PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
package client

import (
	"html"
	"net/url"
	"regexp"
	"strings"
	"unicode"

	"github.com/yuin/goldmark"
	"github.com/yuin/goldmark/ast"
	"github.com/yuin/goldmark/text"
)

var (
	plainURL    = regexp.MustCompile(`(?i)(?:https?://|www\.)[^\s<>]+`)
	loginPrompt = regexp.MustCompile(`(?i)(?:please\s+(?:log\s*in|sign\s*in)|(?:log\s*in|sign\s*in)\s+(?:to\b|or\s+sign\s*up)|(?:login|authentication)\s+required|enable\s+javascript\s+to\s+continue)`)
)

// ClassifyCardContent describes the saved fields only. Metadata, annotations,
// AI insight, link labels, and raw HTML blocks do not establish a body.
func ClassifyCardContent(card *CardDetail) string {
	if card == nil {
		return "empty"
	}
	body, bodyLink := contentEvidence(card.Content)
	if body {
		return "body_available"
	}
	description, descriptionLink := contentEvidence(card.Description)
	if description {
		return "description_only"
	}
	if bodyLink || descriptionLink || isWebURL(card.URL) {
		return "link_only"
	}
	return "empty"
}

func contentEvidence(value string) (bool, bool) {
	value = normalizeContent(value)
	switch strings.ToLower(strings.Trim(value, `"`)) {
	case "", "null", "undefined", "nil":
		return false, false
	}
	source := []byte(value)
	doc := goldmark.New().Parser().Parse(text.NewReader(source))
	var body strings.Builder
	hasLink := plainURL.MatchString(value)
	_ = ast.Walk(doc, func(node ast.Node, entering bool) (ast.WalkStatus, error) {
		if !entering {
			return ast.WalkContinue, nil
		}
		switch n := node.(type) {
		case *ast.Link, *ast.AutoLink, *ast.Image:
			hasLink = true
			return ast.WalkSkipChildren, nil
		case *ast.Text:
			body.Write(n.Segment.Value(source))
			if n.SoftLineBreak() || n.HardLineBreak() {
				body.WriteByte(' ')
			}
		case *ast.String:
			body.Write(n.Value)
		case *ast.CodeBlock, *ast.FencedCodeBlock:
			body.Write(node.Lines().Value(source))
		case *ast.HTMLBlock, *ast.RawHTML:
			return ast.WalkSkipChildren, nil
		}
		if node.Type() == ast.TypeBlock {
			body.WriteByte(' ')
		}
		return ast.WalkContinue, nil
	})
	visible := normalizeContent(plainURL.ReplaceAllString(body.String(), " "))
	// Prompt checks also see link labels, since login pages often consist of
	// nothing but a heading and login buttons. Prefer a false negative here.
	if isContentPlaceholder(value) || isContentPlaceholder(visible) {
		return false, hasLink
	}
	for _, r := range visible {
		if unicode.IsLetter(r) || unicode.IsNumber(r) {
			return true, hasLink
		}
	}
	return false, hasLink
}

func normalizeContent(value string) string {
	value = html.UnescapeString(value)
	value = strings.Map(func(r rune) rune {
		if unicode.Is(unicode.Cf, r) {
			return -1
		}
		return r
	}, value)
	return strings.TrimSpace(value)
}

func isContentPlaceholder(value string) bool {
	compact := strings.Join(strings.Fields(strings.ToLower(value)), " ")
	if loginPrompt.MatchString(compact) {
		return true
	}
	for _, phrase := range []string{
		"请先登录", "请登录", "请先登入", "請先登入", "請登入", "請登錄",
		"登录后查看", "登录后阅读", "登录后继续", "登录即可", "登录以继续",
		"登入後查看", "登入後閱讀", "登入後繼續", "登陆后查看", "登陆后阅读",
		"很抱歉，没有解析为文章", "未解析为文章", "无法解析为文章", "正文获取失败",
	} {
		if strings.Contains(compact, phrase) {
			return true
		}
	}
	compact = strings.Trim(compact, " #*_~`.!。！:：\t\r\n")
	switch compact {
	case "login", "log in", "sign in", "sign up", "登录", "登陆", "登入", "登錄", "注册", "註冊", "登录/注册", "登录 / 注册", "登入/註冊":
		return true
	}
	fields := strings.Fields(compact)
	for _, field := range fields {
		switch strings.Trim(field, `"'`+"`*_~.,;。；") {
		case "null", "undefined", "nil":
		default:
			return false
		}
	}
	return len(fields) > 0
}

func isWebURL(value string) bool {
	value = strings.TrimSpace(value)
	if strings.HasPrefix(strings.ToLower(value), "www.") {
		value = "https://" + value
	}
	u, err := url.Parse(value)
	return err == nil && u.Host != "" && (u.Scheme == "https" || u.Scheme == "http")
}
