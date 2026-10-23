package tagcleanup

import (
	"context"
	"fmt"
	"sort"
	"strings"

	"github.com/OLCUBO/cubox-cli/internal/client"
)

// Store is the Cubox data needed to inspect and delete empty tags.
type Store interface {
	ListTags() ([]client.Tag, error)
	FilterCards(*client.CardFilterRequest) ([]client.Card, error)
	DeleteTags([]string) error
}

type CardReader interface {
	GetCardDetail(string) (*client.CardDetail, error)
}

type TagRef struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

type SkippedTag struct {
	TagRef
	Reason string `json:"reason"`
}

type Report struct {
	Eligible []TagRef     `json:"eligible"`
	Deleted  []TagRef     `json:"deleted"`
	Skipped  []SkippedTag `json:"skipped"`
}

// PreviewAfterDelete predicts which affected tags would be empty after the
// specified cards disappear. It reads all matching pages needed to find a
// survivor, across both active and archived cards.
func PreviewAfterDelete(ctx context.Context, store Store, tags []client.Tag, affected, deleting []string) (Report, error) {
	report := Report{Eligible: []TagRef{}, Deleted: []TagRef{}, Skipped: []SkippedTag{}}
	excluded := map[string]bool{}
	for _, id := range deleting {
		excluded[id] = true
	}
	for _, id := range affected {
		ref, reason, err := inspect(ctx, store, tags, id, excluded)
		if err != nil {
			return report, err
		}
		if reason != "" {
			report.Skipped = append(report.Skipped, SkippedTag{TagRef: ref, Reason: reason})
		} else {
			report.Eligible = append(report.Eligible, ref)
		}
	}
	return report, nil
}

// AffectedTags captures only labels present on the cards about to be deleted.
// It does not mutate Cubox; an unreadable card stops the deletion workflow.
func AffectedTags(reader CardReader, tags []client.Tag, cardIDs []string) ([]string, error) {
	byName := map[string][]string{}
	for _, tag := range tags {
		byName[tag.NestedName] = append(byName[tag.NestedName], tag.ID)
	}
	affected := map[string]bool{}
	for _, id := range cardIDs {
		card, err := reader.GetCardDetail(id)
		if err != nil {
			return nil, fmt.Errorf("reading card %s before deletion: %w", id, err)
		}
		if card == nil || card.ID != id {
			return nil, fmt.Errorf("card detail did not match requested ID %s", id)
		}
		for _, name := range card.Tags {
			// These are durable vocabulary/workflow choices, even when unused.
			// An explicit prune-empty request can still inspect a child tag.
			if strings.HasPrefix(name, "主题/") || strings.HasPrefix(name, "处理/") {
				continue
			}
			matches := byName[name]
			if len(matches) != 1 {
				return nil, fmt.Errorf("card %s tag %q could not be uniquely matched to a tag ID", id, name)
			}
			affected[matches[0]] = true
		}
	}
	ids := make([]string, 0, len(affected))
	for id := range affected {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	return ids, nil
}

// Prune previews by default. Apply checks occupancy again immediately before
// each deletion, then verifies that the tag ID disappeared.
func Prune(ctx context.Context, store Store, ids []string, apply bool) (Report, error) {
	report := Report{Eligible: []TagRef{}, Deleted: []TagRef{}, Skipped: []SkippedTag{}}
	if len(ids) == 0 {
		return report, nil
	}
	seen := map[string]bool{}
	for _, id := range ids {
		if strings.TrimSpace(id) == "" || seen[id] {
			return report, fmt.Errorf("tag IDs must be nonempty and unique")
		}
		seen[id] = true
	}
	tags, err := store.ListTags()
	if err != nil {
		return report, err
	}
	for _, id := range ids {
		if err := ctx.Err(); err != nil {
			return report, err
		}
		tag, reason, err := inspect(ctx, store, tags, id, nil)
		if err != nil {
			return report, err
		}
		if reason != "" {
			report.Skipped = append(report.Skipped, SkippedTag{TagRef: tag, Reason: reason})
			continue
		}
		if !apply {
			report.Eligible = append(report.Eligible, tag)
			continue
		}
		latest, err := store.ListTags()
		if err != nil {
			return report, fmt.Errorf("before deleting tag %s: %w", id, err)
		}
		_, reason, err = inspect(ctx, store, latest, id, nil)
		if err != nil {
			return report, fmt.Errorf("before deleting tag %s: %w", id, err)
		}
		if reason != "" {
			report.Skipped = append(report.Skipped, SkippedTag{TagRef: tag, Reason: "changed before deletion: " + reason})
			continue
		}
		report.Eligible = append(report.Eligible, tag)
		if err := store.DeleteTags([]string{id}); err != nil {
			return report, fmt.Errorf("deleting empty tag %s: %w", id, err)
		}
		verified, err := store.ListTags()
		if err != nil {
			return report, fmt.Errorf("deleted tag %s, but verification failed: %w", id, err)
		}
		for _, remaining := range verified {
			if remaining.ID == id {
				return report, fmt.Errorf("tag %s delete returned success but it still exists", id)
			}
		}
		report.Deleted = append(report.Deleted, tag)
		tags = verified
	}
	return report, nil
}

func inspect(ctx context.Context, store Store, tags []client.Tag, id string, excluded map[string]bool) (TagRef, string, error) {
	var selected *client.Tag
	for i := range tags {
		if tags[i].ID == id {
			selected = &tags[i]
		}
	}
	if selected == nil {
		return TagRef{ID: id}, "tag no longer exists", nil
	}
	ref := TagRef{ID: id, Name: selected.NestedName}
	if selected.ParentID == nil {
		switch selected.Name {
		case "来源", "处理", "skill", "笔记", "主题":
			return ref, "protected root tag", nil
		}
	}
	for _, tag := range tags {
		if tag.ParentID != nil && *tag.ParentID == id {
			return ref, "tag has child tags", nil
		}
	}
	for _, archived := range []bool{false, true} {
		occupied, err := hasOtherCards(ctx, store, id, archived, excluded)
		if err != nil {
			return ref, "", fmt.Errorf("checking %s cards for tag %s: %w", map[bool]string{false: "active", true: "archived"}[archived], id, err)
		}
		if occupied {
			if archived {
				return ref, "archived cards remain", nil
			}
			return ref, "active cards remain", nil
		}
	}
	return ref, "", nil
}

func hasOtherCards(ctx context.Context, store Store, tagID string, archived bool, excluded map[string]bool) (bool, error) {
	limit := 1
	if len(excluded) > 0 {
		limit = 50
	}
	lastID := ""
	for {
		if err := ctx.Err(); err != nil {
			return false, err
		}
		cards, err := store.FilterCards(&client.CardFilterRequest{
			TagFilters: []string{tagID}, Archived: &archived, Limit: limit, LastCardID: lastID,
		})
		if err != nil {
			return false, err
		}
		for _, card := range cards {
			if !excluded[card.ID] {
				return true, nil
			}
		}
		if len(cards) < limit {
			return false, nil
		}
		nextID := cards[len(cards)-1].ID
		if nextID == "" || nextID == lastID {
			return false, fmt.Errorf("card filter did not advance for tag %s", tagID)
		}
		lastID = nextID
	}
}
