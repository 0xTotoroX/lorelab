package client

import "testing"

func TestClassifyCardContent(t *testing.T) {
	t.Parallel()
	linkNullLink := "[social.example](https://social.example/post/1)\n\nnull\n\n[social.example](https://social.example/post/1)\n"
	tests := []struct {
		name, content, description, url, want string
	}{
		{"empty", " \n\t", "", "", "empty"},
		{"null", "null", "null", "", "empty"},
		{"quoted null", `"null"`, "", "", "empty"},
		{"repeated null", "null\n\nnull", "", "", "empty"},
		{"invisible", "\ufeff\u200b\u200c\u00a0", "", "", "empty"},
		{"url", "https://example.com/post/1", "", "", "link_only"},
		{"urls", "https://example.com/one\nhttps://example.com/two", "", "", "link_only"},
		{"autolink", "<https://example.com/post>", "", "", "link_only"},
		{"markdown link", "[Read article](https://example.com/post)", "", "", "link_only"},
		{"nested link", "[A **long** label](https://example.com/a_(b) \"title\")", "", "", "link_only"},
		{"reference link", "[Read][article]\n\n[article]: https://example.com/post", "", "", "link_only"},
		{"link list", "- [First](https://example.com/a)\n- [Second](https://example.com/b)", "", "", "link_only"},
		{"image", "![alt text](https://example.com/image.png)", "", "", "link_only"},
		{"link null link with excerpt", linkNullLink, "An excerpt that stops before the…", "", "description_only"},
		{"link null link without excerpt", linkNullLink, "", "", "link_only"},
		{"link null link null excerpt", linkNullLink, "null", "", "link_only"},
		{"description", "", "A saved excerpt.", "https://example.com", "description_only"},
		{"description link", "null", "[Open](https://example.com)", "", "link_only"},
		{"metadata link", "", "", "https://example.com", "link_only"},
		{"login", "Please log in to continue", "", "https://example.com", "link_only"},
		{"site login", "Log in to Example", "", "https://example.com", "link_only"},
		{"login register", "登录/注册", "", "", "empty"},
		{"login heading", "# Sign in\n\n[Continue](https://example.com/login)", "", "", "link_only"},
		{"login with excerpt", "请先登录后查看全文", "A saved excerpt.", "", "description_only"},
		{"traditional login", "請先登入後閱讀", "", "", "empty"},
		{"login description", "登录", "Sign in to view this page", "", "empty"},
		{"parse placeholder", "很抱歉，没有解析为文章", "", "https://example.com", "link_only"},
		{"javascript placeholder", "Enable JavaScript to continue", "", "", "empty"},
		{"markup only", "---\n\n***", "", "", "empty"},
		{"HTML only", "<div>Please sign in</div>", "", "", "empty"},
		{"body", "# Heading\n\nSome actual body text.", "", "", "body_available"},
		{"body and link", "Actual text with [source](https://example.com).", "", "", "body_available"},
		{"code", "```go\nfmt.Println(42)\n```", "", "", "body_available"},
		{"interface instructions are not full", "Navigation: home, comparison, filters. Click a column to sort the comparison table.", "", "", "body_available"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			card := &CardDetail{Content: tt.content, Description: tt.description, URL: tt.url,
				Title: "Title alone is not body evidence", Insight: &Insight{Summary: "AI text is not body evidence"}}
			if got := ClassifyCardContent(card); got != tt.want {
				t.Fatalf("got %q, want %q", got, tt.want)
			}
		})
	}
}
