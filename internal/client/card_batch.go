// [INPUT]: Client transport/throttle, CardDetail, context, and content classification.
// [OUTPUT]: GetCardBatch and the versioned CardBatch JSON contract.
// [POS]: Bounded, read-only batch orchestration; no original-site retrieval.
// [PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
package client

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"strings"
	"sync"
)

var ErrCardBatchIncomplete = errors.New("card batch incomplete; inspect items for errors and skipped requests")

type CardBatchError struct {
	Code       string `json:"code"`
	Message    string `json:"message"`
	HTTPStatus int    `json:"http_status,omitempty"`
	APICode    *int   `json:"api_code,omitempty"`
}

type CardBatchItem struct {
	ID            string          `json:"id"`
	Status        string          `json:"status"`
	ContentStatus *string         `json:"content_status"`
	Card          *CardDetail     `json:"card"`
	Error         *CardBatchError `json:"error"`
}

type CardBatchCounts struct {
	Total   int `json:"total"`
	OK      int `json:"ok"`
	Error   int `json:"error"`
	Skipped int `json:"skipped"`
}

type CardBatch struct {
	SchemaVersion int             `json:"schema_version"`
	Kind          string          `json:"kind"`
	Items         []CardBatchItem `json:"items"`
	Counts        CardBatchCounts `json:"counts"`
}

// NormalizeCardIDs trims blank entries and deduplicates in first-seen order.
func NormalizeCardIDs(ids []string) []string {
	result := make([]string, 0, len(ids))
	seen := make(map[string]bool, len(ids))
	for _, id := range ids {
		id = strings.TrimSpace(id)
		if id != "" && !seen[id] {
			seen[id] = true
			result = append(result, id)
		}
	}
	return result
}

type cardBatchState struct {
	mu       sync.Mutex
	next     int
	streak   int
	stopped  bool
	admitCtx context.Context
	stop     context.CancelFunc
}

func (s *cardBatchState) take(total int) (int, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.stopped || s.admitCtx.Err() != nil || s.next >= total {
		return 0, false
	}
	i := s.next
	s.next++
	return i, true
}

func (s *cardBatchState) skipReason() *CardBatchError {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.stopped {
		return &CardBatchError{Code: "consecutive_errors", Message: "not started: batch stopped after 3 consecutive errors"}
	}
	if s.admitCtx.Err() != nil {
		return &CardBatchError{Code: "canceled", Message: "not started: batch context canceled or expired"}
	}
	return nil
}

func (s *cardBatchState) complete(failed bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	// A late in-flight success cannot reopen this batch.
	if s.stopped {
		return
	}
	if failed {
		s.streak++
		if s.streak >= maxErrorStreak {
			s.stopped = true
			s.stop()
		}
	} else {
		s.streak = 0
	}
}

// GetCardBatch keeps output in input order while counting consecutive failures
// in completion order. Only admission is canceled on a trip; admitted requests
// finish and retain their results. A returned batch must be consumed even when
// err is ErrCardBatchIncomplete. The caller owns the single shared Client.
func (c *Client) GetCardBatch(ctx context.Context, ids []string, workers int) (*CardBatch, error) {
	if workers < 1 || workers > 4 {
		return nil, fmt.Errorf("workers must be between 1 and 4")
	}
	ids = NormalizeCardIDs(ids)
	if len(ids) == 0 {
		return nil, fmt.Errorf("at least one card ID is required")
	}
	admitCtx, cancel := context.WithCancel(ctx)
	defer cancel()
	state := &cardBatchState{admitCtx: admitCtx, stop: cancel}
	// One HTTP client for the whole batch, sharing c's transport and timeout.
	// Do not follow an API redirect to a login page or the original website.
	batchHTTP := *c.httpClient
	batchHTTP.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	batch := &CardBatch{SchemaVersion: 1, Kind: "cubox_card_batch", Items: make([]CardBatchItem, len(ids))}
	for i, id := range ids {
		batch.Items[i] = CardBatchItem{ID: id, Status: "skipped"}
	}
	var wg sync.WaitGroup
	for w := 0; w < workers && w < len(ids); w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for {
				i, ok := state.take(len(ids))
				if !ok {
					return
				}
				batch.Items[i] = c.readBatchCard(ctx, ids[i], state, &batchHTTP)
			}
		}()
	}
	wg.Wait()
	batch.Counts.Total = len(ids)
	for i := range batch.Items {
		switch batch.Items[i].Status {
		case "ok":
			batch.Counts.OK++
		case "error":
			batch.Counts.Error++
		case "skipped":
			batch.Counts.Skipped++
			batch.Items[i].Error = state.skipReason()
		}
	}
	if batch.Counts.Error > 0 || batch.Counts.Skipped > 0 {
		return batch, ErrCardBatchIncomplete
	}
	return batch, nil
}

func (c *Client) readBatchCard(ctx context.Context, id string, state *cardBatchState, httpClient *http.Client) CardBatchItem {
	item := CardBatchItem{ID: id, Status: "skipped"}
	if c.throttleContext(state.admitCtx) != nil || state.skipReason() != nil {
		return item
	}
	// Admission has succeeded. Use the caller's context, not the stop context,
	// so an error streak does not discard responses already in flight.
	item.Status = "error"
	defer func() { state.complete(item.Status == "error") }()
	endpoint := c.baseURL + "/c/api/cli/card/detail?" + url.Values{"id": {id}}.Encode()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint, nil)
	if err != nil {
		item.Error = &CardBatchError{Code: "invalid_request", Message: "could not construct card detail request"}
		return item
	}
	data, err := c.sendRequestAuth(req, false, httpClient)
	if err != nil {
		item.Error = safeCardBatchError(err)
		return item
	}
	var detail *CardDetail
	if err := json.Unmarshal(data, &detail); err != nil || detail == nil {
		item.Error = &CardBatchError{Code: "invalid_card_detail", Message: "response does not contain a valid card detail"}
		return item
	}
	if detail.ID != id {
		item.Error = &CardBatchError{Code: "id_mismatch", Message: "returned card ID does not match requested ID"}
		return item
	}
	contentStatus := ClassifyCardContent(detail)
	item.Status, item.ContentStatus, item.Card = "ok", &contentStatus, detail
	return item
}

// Never echo API messages, response bodies, URLs, or transport error strings:
// any of them can contain credentials or server-controlled text.
func safeCardBatchError(err error) *CardBatchError {
	var apiErr *apiError
	var httpErr *httpError
	switch {
	case errors.As(err, &apiErr):
		return &CardBatchError{Code: "api_error", Message: "Cubox API rejected the request", APICode: &apiErr.code}
	case errors.As(err, &httpErr):
		return &CardBatchError{Code: "http_error", Message: "Cubox returned an unsuccessful HTTP status", HTTPStatus: httpErr.status}
	case errors.Is(err, context.DeadlineExceeded):
		return &CardBatchError{Code: "timeout", Message: "card detail request timed out"}
	case errors.Is(err, context.Canceled):
		return &CardBatchError{Code: "canceled", Message: "card detail request canceled"}
	default:
		return &CardBatchError{Code: "request_failed", Message: "card detail request or response decoding failed"}
	}
}
