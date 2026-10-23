package topic

import (
	"context"
	"strings"
	"testing"

	"github.com/OLCUBO/cubox-cli/internal/client"
)

type fakeStore struct {
	tags      []client.Tag
	card      client.CardDetail
	addCalls  int
	added     []string
	listCalls int
	changeTag bool
}

func (s *fakeStore) ListFolders() ([]client.Folder, error) {
	return []client.Folder{{ID: "folder-1", Name: "Skills 与 MCP", NestedName: "AI 与智能体/Agent 与自动化/Skills 与 MCP"}}, nil
}

func (s *fakeStore) ListTags() ([]client.Tag, error) {
	s.listCalls++
	if s.changeTag && s.listCalls > 1 {
		return s.tags[:1], nil
	}
	return s.tags, nil
}

func (s *fakeStore) GetCardDetail(id string) (*client.CardDetail, error) {
	card := s.card
	card.Tags = append([]string(nil), s.card.Tags...)
	return &card, nil
}

func (s *fakeStore) AddCardTags(req *client.CardAddTagsRequest) error {
	s.addCalls++
	s.added = append([]string(nil), req.AddTagNestedNames...)
	s.card.Tags = append(s.card.Tags, req.AddTagNestedNames...)
	return nil
}

type fakeClassifier struct {
	decision Decision
	calls    int
	input    Input
}

func (f *fakeClassifier) Classify(_ context.Context, input Input) (Decision, error) {
	f.calls++
	f.input = input
	return f.decision, nil
}

func parent(id string) *string { return &id }

func testStore() *fakeStore {
	return &fakeStore{
		tags: []client.Tag{
			{ID: "root", Name: "主题", NestedName: "主题"},
			{ID: "mcp", Name: "MCP", NestedName: "主题/MCP", ParentID: parent("root")},
			{ID: "km", Name: "知识管理", NestedName: "主题/知识管理", ParentID: parent("root")},
			{ID: "source", Name: "来源", NestedName: "来源"},
		},
		card: client.CardDetail{
			ID: "card-1", Title: "Obsidian MCP", Content: strings.Repeat("文章正文讨论 MCP 与知识管理。", 12),
			Tags:   []string{"来源/GitHub", "处理/00 待审", "skill"},
			Folder: &client.Folder{ID: "folder-1", Name: "Skills 与 MCP"},
		},
	}
}

func TestProcessPreviewKeepsModelPriorityWithoutWriting(t *testing.T) {
	store := testStore()
	model := &fakeClassifier{decision: Decision{
		Sufficient: true, TopicIDs: []string{"km", "mcp"}, Suggested: []string{"跨设备同步"}, Reason: "两个主题都在正文中",
	}}
	result, err := Process(context.Background(), store, model, "card-1", false)
	if err != nil {
		t.Fatal(err)
	}
	if result.Status != "preview" || len(result.Topics) != 2 || result.Topics[0] != "主题/知识管理" || result.Topics[1] != "主题/MCP" {
		t.Fatalf("priority was not preserved: %+v", result)
	}
	if len(result.Suggested) != 1 || store.addCalls != 0 || model.input.Evidence != "content" ||
		model.input.Folder != "AI 与智能体/Agent 与自动化/Skills 与 MCP" {
		t.Fatalf("preview wrote tags or lost evidence: %+v", result)
	}
}

func TestProcessApplyAddsOnlyMissingApprovedTopic(t *testing.T) {
	store := testStore()
	store.card.Tags = append(store.card.Tags, "主题/MCP")
	model := &fakeClassifier{decision: Decision{
		Sufficient: true, TopicIDs: []string{"mcp", "km"}, Suggested: []string{"新词"},
	}}
	result, err := Process(context.Background(), store, model, "card-1", true)
	if err != nil {
		t.Fatal(err)
	}
	if result.Status != "applied" || store.addCalls != 1 || len(store.added) != 1 || store.added[0] != "主题/知识管理" {
		t.Fatalf("unexpected apply: result=%+v added=%v", result, store.added)
	}
	for _, old := range []string{"来源/GitHub", "处理/00 待审", "skill", "主题/MCP"} {
		if len(missing([]string{old}, store.card.Tags)) != 0 {
			t.Fatalf("original tag %q was removed", old)
		}
	}
	if len(missing([]string{"主题/新词"}, store.card.Tags)) == 0 {
		t.Fatal("new-topic suggestion was created")
	}
}

func TestInsufficientContentDoesNotCallModel(t *testing.T) {
	store := testStore()
	store.card.Content = "# 文章解析\n\n很抱歉，没有解析为文章"
	store.card.Description = "short"
	model := &fakeClassifier{}
	result, err := Process(context.Background(), store, model, "card-1", true)
	if err != nil || result.Status != "insufficient" || model.calls != 0 || store.addCalls != 0 {
		t.Fatalf("insufficient content should not write: result=%+v err=%v", result, err)
	}
}

func TestDescriptionFallbackAllowsAtMostOneTopic(t *testing.T) {
	store := testStore()
	store.card.Content = "# 文章解析\n\n很抱歉，没有解析为文章"
	store.card.Description = strings.Repeat("描述明确讨论 MCP 与插件。", 12)
	model := &fakeClassifier{decision: Decision{Sufficient: true, TopicIDs: []string{"mcp", "km"}}}
	_, err := Process(context.Background(), store, model, "card-1", true)
	if err == nil || model.input.Evidence != "description" || model.input.MaxTopics != 1 || store.addCalls != 0 {
		t.Fatalf("description-only classification exceeded one topic: %v", err)
	}
}

func TestDescriptionFallbackCanApplyOneApprovedTopic(t *testing.T) {
	store := testStore()
	store.card.Content = "# 文章解析\n\n很抱歉，没有解析为文章"
	store.card.Description = strings.Repeat("描述明确讨论 MCP 与插件。", 12)
	model := &fakeClassifier{decision: Decision{Sufficient: true, TopicIDs: []string{"mcp"}}}
	result, err := Process(context.Background(), store, model, "card-1", true)
	if err != nil || result.Status != "applied" || len(store.added) != 1 || store.added[0] != "主题/MCP" {
		t.Fatalf("description fallback failed: result=%+v added=%v err=%v", result, store.added, err)
	}
	if model.input.Content != "" || model.input.MaxTopics != 1 {
		t.Fatalf("unexpected fallback input: %+v", model.input)
	}
}

func TestAlreadyTaggedCardDoesNotWriteAgain(t *testing.T) {
	store := testStore()
	store.card.Tags = append(store.card.Tags, "主题/MCP")
	model := &fakeClassifier{decision: Decision{Sufficient: true, TopicIDs: []string{"mcp"}}}
	result, err := Process(context.Background(), store, model, "card-1", true)
	if err != nil || result.Status != "no_change" || store.addCalls != 0 {
		t.Fatalf("expected idempotent no-op: result=%+v err=%v", result, err)
	}
}

func TestSuggestionsExcludeApprovedAndRootLabels(t *testing.T) {
	store := testStore()
	model := &fakeClassifier{decision: Decision{
		Sufficient: true, Suggested: []string{"MCP", "来源", "跨设备同步"},
	}}
	result, err := Process(context.Background(), store, model, "card-1", false)
	if err != nil || len(result.Suggested) != 1 || result.Suggested[0] != "跨设备同步" {
		t.Fatalf("unexpected suggestions: %+v err=%v", result, err)
	}
}

func TestUnknownTopicAndVocabularyDriftStopBeforeWrite(t *testing.T) {
	store := testStore()
	model := &fakeClassifier{decision: Decision{Sufficient: true, TopicIDs: []string{"unknown"}}}
	if _, err := Process(context.Background(), store, model, "card-1", true); err == nil || store.addCalls != 0 {
		t.Fatal("unapproved topic was not rejected")
	}
	store = testStore()
	store.changeTag = true
	model.decision.TopicIDs = []string{"mcp"}
	if _, err := Process(context.Background(), store, model, "card-1", true); err == nil || store.addCalls != 0 {
		t.Fatal("changed approved vocabulary was not rejected")
	}
}

func TestNoApprovedTopicsRequiresReviewBeforeApply(t *testing.T) {
	store := testStore()
	store.tags = nil
	model := &fakeClassifier{decision: Decision{Sufficient: true, Suggested: []string{"MCP"}}}
	preview, err := Process(context.Background(), store, model, "card-1", false)
	if err != nil || len(preview.Topics) != 0 || len(preview.Suggested) != 1 || store.addCalls != 0 {
		t.Fatalf("expected suggestions-only preview: %+v %v", preview, err)
	}
	if _, err := Process(context.Background(), store, model, "card-1", true); err == nil || store.addCalls != 0 {
		t.Fatal("apply succeeded without approved topics")
	}
}

func TestThreeTopicTotalLimit(t *testing.T) {
	store := testStore()
	store.card.Tags = append(store.card.Tags, "主题/MCP", "主题/旧主题A", "主题/旧主题B")
	model := &fakeClassifier{decision: Decision{Sufficient: true, TopicIDs: []string{"km"}}}
	if _, err := Process(context.Background(), store, model, "card-1", true); err == nil || store.addCalls != 0 {
		t.Fatal("fourth topic was not rejected")
	}
}

func TestSuggestionsAndApprovedSelectionsShareTopicLimit(t *testing.T) {
	store := testStore()
	model := &fakeClassifier{decision: Decision{
		Sufficient: true, TopicIDs: []string{"mcp", "km"}, Suggested: []string{"跨设备同步", "自动化"},
	}}
	if _, err := Process(context.Background(), store, model, "card-1", false); err == nil {
		t.Fatal("four proposed topics were accepted")
	}
}
