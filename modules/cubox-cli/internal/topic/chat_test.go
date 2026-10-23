package topic

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestChatClassifierSendsDataAndParsesDecision(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.Header.Get("Authorization") != "Bearer test-key" {
			t.Errorf("unexpected request: %s %s", r.Method, r.Header.Get("Authorization"))
		}
		var body struct {
			Model    string `json:"model"`
			Messages []struct {
				Role    string `json:"role"`
				Content string `json:"content"`
			} `json:"messages"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Error(err)
		}
		if body.Model != "test-model" || len(body.Messages) != 2 || body.Messages[0].Role != "system" || body.Messages[1].Role != "user" {
			t.Errorf("unexpected model request: %+v", body)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"choices":[{"message":{"content":"{\"sufficient\":true,\"topic_ids\":[\"mcp\"],\"suggested_new_topics\":[],\"reason\":\"central topic\"}"}}]}`))
	}))
	defer server.Close()
	classifier, err := NewChatClassifier(server.URL, "test-key", "test-model")
	if err != nil {
		t.Fatal(err)
	}
	decision, err := classifier.Classify(context.Background(), Input{Title: "MCP", Evidence: "content", Approved: []ApprovedTopic{{ID: "mcp", Name: "主题/MCP"}}, MaxTopics: 3})
	if err != nil || !decision.Sufficient || len(decision.TopicIDs) != 1 || decision.TopicIDs[0] != "mcp" {
		t.Fatalf("unexpected model decision: %+v %v", decision, err)
	}
}

func TestChatClassifierRejectsUnconfiguredOrInsecureRemote(t *testing.T) {
	if _, err := NewChatClassifier("", "", "m"); err == nil {
		t.Fatal("missing endpoint was accepted")
	}
	if _, err := NewChatClassifier("http://example.com/v1/chat/completions", "key", "m"); err == nil {
		t.Fatal("insecure remote endpoint was accepted")
	}
	if _, err := NewChatClassifier("https://example.com/v1/chat/completions", "", "m"); err == nil {
		t.Fatal("missing remote key was accepted")
	}
}

func TestChatClassifierConsolidatesCandidates(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Messages []struct {
				Content string `json:"content"`
			} `json:"messages"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Error(err)
		}
		if len(body.Messages) != 2 || body.Messages[0].Content != consolidationInstructions {
			t.Errorf("consolidation instructions missing: %+v", body)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"choices":[{"message":{"content":"{\"assignments\":[{\"name\":\"检索增强生成\",\"target\":\"RAG\",\"supported_card_ids\":[\"b\"]}]}"}}]}`))
	}))
	defer server.Close()
	classifier, err := NewChatClassifier(server.URL, "", "mock")
	if err != nil {
		t.Fatal(err)
	}
	result, err := classifier.Consolidate(context.Background(), ConsolidationInput{Candidates: []CandidateEvidence{{Name: "检索增强生成"}}})
	if err != nil || len(result.Assignments) != 1 || result.Assignments[0].Target != "RAG" {
		t.Fatalf("unexpected consolidation: %+v %v", result, err)
	}
}
