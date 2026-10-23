package topic

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"unicode/utf8"

	"github.com/OLCUBO/cubox-cli/internal/client"
)

const (
	maxTopics = 3
	minText   = 120
)

// Store is the Cubox data needed to classify and add topics to one card.
type Store interface {
	ListTags() ([]client.Tag, error)
	ListFolders() ([]client.Folder, error)
	GetCardDetail(string) (*client.CardDetail, error)
	AddCardTags(*client.CardAddTagsRequest) error
}

type ApprovedTopic struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

type Input struct {
	Title       string            `json:"title"`
	Description string            `json:"description,omitempty"`
	Content     string            `json:"content,omitempty"`
	Folder      string            `json:"folder,omitempty"`
	Evidence    string            `json:"evidence"`
	Existing    []string          `json:"existing_tags"`
	Approved    []ApprovedTopic   `json:"approved_topics"`
	Aliases     map[string]string `json:"reviewed_aliases,omitempty"`
	Rejected    []string          `json:"rejected_topics,omitempty"`
	MaxTopics   int               `json:"max_topics"`
}

type Decision struct {
	Sufficient bool     `json:"sufficient"`
	TopicIDs   []string `json:"topic_ids"`
	Suggested  []string `json:"suggested_new_topics"`
	Reason     string   `json:"reason"`
}

type Classifier interface {
	Classify(context.Context, Input) (Decision, error)
}

type Result struct {
	CardID    string   `json:"card_id"`
	Title     string   `json:"title"`
	Status    string   `json:"status"`
	Evidence  string   `json:"evidence"`
	Topics    []string `json:"topics"`
	Added     []string `json:"added"`
	Suggested []string `json:"suggested_new_topics"`
	Reason    string   `json:"reason,omitempty"`
}

// Process previews by default. apply adds only approved, existing topic tags.
func Process(ctx context.Context, store Store, classifier Classifier, cardID string, apply bool) (Result, error) {
	result := Result{CardID: cardID, Topics: []string{}, Added: []string{}, Suggested: []string{}}
	tags, err := store.ListTags()
	if err != nil {
		return result, err
	}
	approved := approvedTopics(tags)
	card, err := store.GetCardDetail(cardID)
	if err != nil {
		return result, err
	}
	if card == nil || card.ID != cardID {
		return result, fmt.Errorf("card detail did not match requested ID %s", cardID)
	}
	result.Title = card.Title
	content, evidence, maxAllowed := evidenceText(card)
	result.Evidence = evidence
	if evidence == "insufficient" {
		result.Status = "insufficient"
		result.Reason = "正文与描述不足，未按标题猜测主题"
		return result, nil
	}
	if apply && len(approved) == 0 {
		return result, fmt.Errorf("no approved 主题/* tags exist; review and create a topic vocabulary before --apply")
	}
	if classifier == nil {
		return result, fmt.Errorf("topic classifier is not configured")
	}
	input := Input{
		Title: card.Title, Description: truncateRunes(card.Description, 4000), Content: content,
		Evidence: evidence, Existing: card.Tags, Approved: approved, MaxTopics: maxAllowed,
	}
	if card.Folder != nil {
		input.Folder = card.Folder.NestedName
		if input.Folder == "" {
			input.Folder = card.Folder.Name
		}
		folders, err := store.ListFolders()
		if err == nil {
			for _, folder := range folders {
				if folder.ID == card.Folder.ID && folder.NestedName != "" {
					input.Folder = folder.NestedName
					break
				}
			}
		}
	}
	decision, err := classifier.Classify(ctx, input)
	if err != nil {
		return result, err
	}
	selected, suggested, err := validateDecision(decision, approved, card.Tags, maxAllowed)
	if err != nil {
		return result, err
	}
	result.Topics = selected
	result.Suggested = suggested
	result.Reason = truncateRunes(decision.Reason, 300)
	if !decision.Sufficient {
		result.Status = "insufficient"
		return result, nil
	}
	result.Status = "preview"
	if !apply {
		return result, nil
	}
	added := missing(selected, card.Tags)
	if len(added) == 0 {
		result.Status = "no_change"
		return result, nil
	}
	// Recheck both the approved vocabulary and card before a name-based API write.
	latestTags, err := store.ListTags()
	if err != nil {
		return result, err
	}
	if !sameApprovedTopics(approved, approvedTopics(latestTags)) {
		return result, fmt.Errorf("approved topic vocabulary changed during classification; no tags were added")
	}
	latestCard, err := store.GetCardDetail(cardID)
	if err != nil {
		return result, err
	}
	if latestCard == nil || latestCard.ID != cardID || latestCard.Title != card.Title ||
		latestCard.Description != card.Description || latestCard.Content != card.Content {
		return result, fmt.Errorf("card content changed during classification; no tags were added")
	}
	if len(missing(card.Tags, latestCard.Tags)) != 0 {
		return result, fmt.Errorf("card tags changed during classification; no tags were added")
	}
	if _, _, err := validateDecision(decision, approved, latestCard.Tags, maxAllowed); err != nil {
		return result, fmt.Errorf("card tags changed during classification: %w", err)
	}
	added = missing(selected, latestCard.Tags)
	if len(added) == 0 {
		result.Status = "no_change"
		return result, nil
	}
	if err := store.AddCardTags(&client.CardAddTagsRequest{ID: cardID, AddTagNestedNames: added}); err != nil {
		return result, err
	}
	verified, err := store.GetCardDetail(cardID)
	if err != nil {
		return result, fmt.Errorf("tags were added, but verification failed: %w", err)
	}
	if verified == nil || verified.ID != cardID || folderID(verified) != folderID(latestCard) ||
		len(missing(latestCard.Tags, verified.Tags)) != 0 ||
		len(missing(added, verified.Tags)) != 0 {
		return result, fmt.Errorf("tag update returned success, but folder or tags could not be verified")
	}
	result.Added = added
	result.Status = "applied"
	return result, nil
}

func folderID(card *client.CardDetail) string {
	if card.Folder == nil {
		return ""
	}
	return card.Folder.ID
}

func approvedTopics(tags []client.Tag) []ApprovedTopic {
	parentID := ""
	for _, tag := range tags {
		if tag.Name == "主题" && tag.ParentID == nil {
			parentID = tag.ID
			break
		}
	}
	result := []ApprovedTopic{}
	if parentID == "" {
		return result
	}
	for _, tag := range tags {
		if tag.ParentID != nil && *tag.ParentID == parentID && tag.NestedName == "主题/"+tag.Name {
			result = append(result, ApprovedTopic{ID: tag.ID, Name: tag.NestedName})
		}
	}
	sort.Slice(result, func(i, j int) bool { return result[i].Name < result[j].Name })
	return result
}

func evidenceText(card *client.CardDetail) (string, string, int) {
	content := strings.TrimSpace(card.Content)
	if strings.Contains(content, "很抱歉，没有解析为文章") {
		content = ""
	}
	if utf8.RuneCountInString(content) >= minText {
		return truncateRunes(content, 20000), "content", maxTopics
	}
	if utf8.RuneCountInString(strings.TrimSpace(card.Description)) >= minText {
		return "", "description", 1
	}
	return "", "insufficient", 0
}

func truncateRunes(s string, max int) string {
	runes := []rune(s)
	if len(runes) <= max {
		return s
	}
	return string(runes[:max*3/4]) + "\n[中间省略]\n" + string(runes[len(runes)-max/4:])
}

func validateDecision(d Decision, approved []ApprovedTopic, existing []string, maxAllowed int) ([]string, []string, error) {
	if len(d.TopicIDs) > maxAllowed || len(d.TopicIDs) > maxTopics {
		return nil, nil, fmt.Errorf("model returned too many topic tags")
	}
	if !d.Sufficient && len(d.TopicIDs) > 0 {
		return nil, nil, fmt.Errorf("model marked evidence insufficient but returned topic tags")
	}
	if !d.Sufficient && len(d.Suggested) > 0 {
		return nil, nil, fmt.Errorf("model marked evidence insufficient but suggested new topics")
	}
	byID := make(map[string]string, len(approved))
	approvedNames := make(map[string]bool, len(approved))
	for _, tag := range approved {
		byID[tag.ID] = tag.Name
		approvedNames[strings.TrimPrefix(tag.Name, "主题/")] = true
	}
	selected := []string{}
	seen := map[string]bool{}
	for _, id := range d.TopicIDs {
		name, ok := byID[id]
		if !ok {
			return nil, nil, fmt.Errorf("model returned unapproved topic ID %q", id)
		}
		if seen[id] {
			return nil, nil, fmt.Errorf("model returned duplicate topic ID %q", id)
		}
		seen[id] = true
		selected = append(selected, name)
	}
	allTopics := map[string]bool{}
	for _, name := range existing {
		if strings.HasPrefix(name, "主题/") {
			allTopics[name] = true
		}
	}
	for _, name := range selected {
		allTopics[name] = true
	}
	if len(allTopics) > maxTopics {
		return nil, nil, fmt.Errorf("card would have more than %d topic tags", maxTopics)
	}
	if len(d.Suggested) > maxTopics {
		return nil, nil, fmt.Errorf("model returned too many new topic suggestions")
	}
	suggested := []string{}
	seenNames := map[string]bool{}
	for _, raw := range d.Suggested {
		name := strings.TrimSpace(raw)
		if name == "" || strings.Contains(name, "/") || utf8.RuneCountInString(name) > 40 {
			return nil, nil, fmt.Errorf("model returned an invalid new topic suggestion")
		}
		if approvedNames[name] || name == "主题" || name == "来源" || name == "处理" || name == "skill" || name == "笔记" {
			continue
		}
		if !seenNames[name] {
			seenNames[name] = true
			suggested = append(suggested, name)
		}
	}
	if len(selected)+len(suggested) > maxAllowed {
		return nil, nil, fmt.Errorf("model returned more than %d topic choices including suggestions", maxAllowed)
	}
	return selected, suggested, nil
}

func missing(want, have []string) []string {
	set := make(map[string]bool, len(have))
	for _, name := range have {
		set[name] = true
	}
	result := []string{}
	for _, name := range want {
		if !set[name] {
			result = append(result, name)
		}
	}
	return result
}

func sameApprovedTopics(a, b []ApprovedTopic) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}
