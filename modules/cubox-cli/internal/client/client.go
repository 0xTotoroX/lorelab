// [INPUT]: HTTP transport, API response types, and shared request admission.
// [OUTPUT]: Client API operations; sendRequestAuth is reused by card batches.
// [POS]: Shared transport for CLI and web/app API groups.
// [PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
package client

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"
)

type Client struct {
	baseURL    string
	token      string
	httpClient *http.Client

	// Safety: global request throttle + consecutive-error circuit breaker.
	// Added after a 2026-10-09 incident where an unthrottled debug loop
	// triggered server-side account state corruption.
	mu        sync.Mutex
	lastReq   time.Time
	errStreak int
}

const (
	minRequestInterval = 500 * time.Millisecond
	maxErrorStreak     = 3
)

// throttle enforces a global minimum interval between requests.
func (c *Client) throttle() {
	_ = c.throttleContext(context.Background())
}

// throttleContext shares the same clock across every worker. Waiting never
// holds mu, so response completion and batch cancellation remain observable.
func (c *Client) throttleContext(ctx context.Context) error {
	for {
		c.mu.Lock()
		if err := ctx.Err(); err != nil {
			c.mu.Unlock()
			return err
		}
		wait := minRequestInterval - time.Since(c.lastReq)
		if wait <= 0 {
			c.lastReq = time.Now()
			c.mu.Unlock()
			return nil
		}
		c.mu.Unlock()
		timer := time.NewTimer(wait)
		select {
		case <-ctx.Done():
			timer.Stop()
			return ctx.Err()
		case <-timer.C:
		}
	}
}

// noteError records an API error for the circuit breaker; noteSuccess resets it.
func (c *Client) noteError() error {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.errStreak++
	if c.errStreak >= maxErrorStreak {
		return fmt.Errorf("circuit breaker tripped: %d consecutive API errors — aborting to protect the account; check the server state before retrying", c.errStreak)
	}
	return nil
}

func (c *Client) noteSuccess() {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.errStreak = 0
}

func New(baseURL, token string) *Client {
	return &Client{
		baseURL: baseURL,
		token:   token,
		httpClient: &http.Client{
			Timeout: 30 * time.Second,
		},
	}
}

func (c *Client) get(path string, params map[string]string) (json.RawMessage, error) {
	u, err := url.Parse(c.baseURL + path)
	if err != nil {
		return nil, fmt.Errorf("invalid URL: %w", err)
	}
	if len(params) > 0 {
		q := u.Query()
		for k, v := range params {
			q.Set(k, v)
		}
		u.RawQuery = q.Encode()
	}
	req, err := http.NewRequest("GET", u.String(), nil)
	if err != nil {
		return nil, err
	}
	return c.doRequest(req)
}

func (c *Client) post(path string, body interface{}) (json.RawMessage, error) {
	jsonBody, err := json.Marshal(body)
	if err != nil {
		return nil, fmt.Errorf("marshalling request body: %w", err)
	}
	req, err := http.NewRequest("POST", c.baseURL+path, bytes.NewReader(jsonBody))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	return c.doRequest(req)
}

func (c *Client) doRequest(req *http.Request) (json.RawMessage, error) {
	return c.doRequestAuth(req, false)
}

// doRequestAuth executes the request with one of the two auth styles used by
// cubox.pro:
//
//   - CLI group (/c/api/cli/*):  "Authorization: Bearer <api-extension-token>"
//   - Web/App group (/c/api/*):  "Authorization: <app-login-token>"  (bare)
//
// The two groups use different token systems; the bare form is required by
// the web app and the native Cubox.app (verified against the app's own
// requests). The web/app group also expects a Cubox-app-like User-Agent —
// requests with Go's default UA were observed failing with -1006 while the
// identical request with the app UA succeeded. See cmd/folder.go for the
// commands that use the web group.
func (c *Client) doRequestAuth(req *http.Request, bare bool) (json.RawMessage, error) {
	c.throttle()
	data, err := c.sendRequestAuth(req, bare, c.httpClient)
	var apiErr *apiError
	if errors.As(err, &apiErr) {
		if cbErr := c.noteError(); cbErr != nil {
			return nil, cbErr
		}
	} else if err == nil {
		c.noteSuccess()
	}
	return data, err
}

// sendRequestAuth performs an already admitted request. Ordinary commands keep
// their error semantics; batches count complete, ID-validated outcomes instead.
func (c *Client) sendRequestAuth(req *http.Request, bare bool, httpClient *http.Client) (json.RawMessage, error) {
	if bare {
		req.Header.Set("Authorization", c.token)
		req.Header.Set("User-Agent", "Cubox/8.3.1 (com.linnk.Linnk; build:668; macOS(Catalyst) 27.0.0) Alamofire/5.10.2")
		req.Header.Set("Accept", "*/*")
	} else {
		req.Header.Set("Authorization", "Bearer "+c.token)
	}

	resp, err := httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("request failed: %w", err)
	}
	defer resp.Body.Close()

	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("reading response: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		return nil, &httpError{status: resp.StatusCode, body: string(data)}
	}

	var apiResp APIResponse
	if err := json.Unmarshal(data, &apiResp); err != nil {
		return nil, fmt.Errorf("parsing response: %w", err)
	}
	if apiResp.Code != 200 {
		return nil, &apiError{code: apiResp.Code, message: apiResp.Message}
	}
	return apiResp.Data, nil
}

type apiError struct {
	code    int
	message string
}

func (e *apiError) Error() string { return fmt.Sprintf("API error %d: %s", e.code, e.message) }

type httpError struct {
	status int
	body   string
}

func (e *httpError) Error() string { return fmt.Sprintf("HTTP %d: %s", e.status, e.body) }

func (c *Client) ListFolders() ([]Folder, error) {
	data, err := c.get("/c/api/cli/folder/list", nil)
	if err != nil {
		return nil, err
	}
	var folders []Folder
	if err := json.Unmarshal(data, &folders); err != nil {
		return nil, fmt.Errorf("parsing folders: %w", err)
	}
	return folders, nil
}

func (c *Client) ListTags() ([]Tag, error) {
	data, err := c.get("/c/api/cli/tag/list", nil)
	if err != nil {
		return nil, err
	}
	var tags []Tag
	if err := json.Unmarshal(data, &tags); err != nil {
		return nil, fmt.Errorf("parsing tags: %w", err)
	}
	return tags, nil
}

func (c *Client) UpdateTag(req *TagUpdateRequest) error {
	_, err := c.post("/c/api/cli/tag/update", req)
	return err
}

func (c *Client) DeleteTags(ids []string) error {
	_, err := c.post("/c/api/cli/tags/delete", ids)
	return err
}

func (c *Client) MergeTags(req *TagMergeRequest) error {
	_, err := c.post("/c/api/cli/tag/merge", req)
	return err
}

func (c *Client) FilterCards(req *CardFilterRequest) ([]Card, error) {
	data, err := c.post("/c/api/cli/card/filter", req)
	if err != nil {
		return nil, err
	}
	var cards []Card
	if err := json.Unmarshal(data, &cards); err != nil {
		return nil, fmt.Errorf("parsing cards: %w", err)
	}
	return cards, nil
}

func (c *Client) GetCardDetail(id string) (*CardDetail, error) {
	data, err := c.get("/c/api/cli/card/detail", map[string]string{"id": id})
	if err != nil {
		return nil, err
	}
	var detail CardDetail
	if err := json.Unmarshal(data, &detail); err != nil {
		return nil, fmt.Errorf("parsing card detail: %w", err)
	}
	return &detail, nil
}

// SaveCards saves cards via the CLI group. Returns the response payload so
// callers can verify. NOTE: the server silently truncates batches larger
// than ~20 entries (verified live 2026-10-09: 50/entry batches saved only the
// first 20 while still returning success) — always batch to <= 20.
func (c *Client) SaveCards(req *SaveCardsRequest) (json.RawMessage, error) {
	return c.post("/c/api/cli/cards/save", req)
}

func (c *Client) UpdateCard(req *CardUpdateRequest) error {
	_, err := c.post("/c/api/cli/card/update", req)
	return err
}

func (c *Client) AddCardTags(req *CardAddTagsRequest) error {
	_, err := c.post("/c/api/cli/card/add/tags", req)
	return err
}

func (c *Client) RemoveCardTags(req *CardRemoveTagsRequest) error {
	_, err := c.post("/c/api/cli/card/remove/tags", req)
	return err
}

func (c *Client) RagQueryCards(query string) ([]Card, error) {
	data, err := c.post("/c/api/cli/card/rag/query", &RagQueryRequest{Query: query})
	if err != nil {
		return nil, err
	}
	var cards []Card
	if err := json.Unmarshal(data, &cards); err != nil {
		return nil, fmt.Errorf("parsing rag results: %w", err)
	}
	return cards, nil
}

func (c *Client) DeleteCards(ids []string) error {
	_, err := c.post("/c/api/cli/cards/delete", ids)
	return err
}

func (c *Client) ArchiveCards(ids []string) error {
	_, err := c.post("/c/api/cli/cards/archiving", ids)
	return err
}

func (c *Client) MoveCards(req *MoveCardsRequest) error {
	_, err := c.post("/c/api/cli/cards/move", req)
	return err
}

func (c *Client) FilterAnnotations(req *AnnotationFilterRequest) ([]Annotation, error) {
	data, err := c.post("/c/api/cli/annotation/filter", req)
	if err != nil {
		return nil, err
	}
	var annotations []Annotation
	if err := json.Unmarshal(data, &annotations); err != nil {
		return nil, fmt.Errorf("parsing annotations: %w", err)
	}
	return annotations, nil
}

// ---- Web/App API group (bare-token auth) ----
//
// Folder write operations (create/rename/delete/move) only exist in the
// web/app group. They are the same endpoints the Cubox web app and the
// native Cubox.app call. The client must be constructed with the app login
// token (see config.LoadAppToken).

func (c *Client) webRequest(method, path string, body interface{}) (json.RawMessage, error) {
	var rdr io.Reader
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return nil, fmt.Errorf("marshalling request body: %w", err)
		}
		rdr = bytes.NewReader(b)
	}
	req, err := http.NewRequest(method, c.baseURL+path, rdr)
	if err != nil {
		return nil, err
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	return c.doRequestAuth(req, true)
}

// WebListGroups returns all folders via GET /c/api/v2/group/my.
func (c *Client) WebListGroups() ([]WebGroup, error) {
	data, err := c.webRequest("GET", "/c/api/v2/group/my", nil)
	if err != nil {
		return nil, err
	}
	var groups []WebGroup
	if err := json.Unmarshal(data, &groups); err != nil {
		return nil, fmt.Errorf("parsing groups: %w", err)
	}
	return groups, nil
}

// WebCreateFolder creates a folder via POST /c/api/group/new.
// parentID may be empty for a root-level folder.
// The endpoint expects application/x-www-form-urlencoded input.
func (c *Client) WebCreateFolder(name, parentID string) (json.RawMessage, error) {
	form := url.Values{"groupName": {name}}
	if parentID != "" {
		form.Set("parentGroupId", parentID)
	}
	return c.webPostForm("/c/api/group/new", form)
}

// WebUpdateFolder updates a folder via POST /c/api/group/update
// (form-urlencoded). A non-empty parentID also moves the folder under that
// parent (verified live: the endpoint accepts parentGroupId alongside
// groupName; omitting groupName trips its "name must not be blank" check).
func (c *Client) WebUpdateFolder(id, name, parentID string) (json.RawMessage, error) {
	form := url.Values{"groupId": {id}, "groupName": {name}}
	if parentID != "" {
		form.Set("parentGroupId", parentID)
	}
	return c.webPostForm("/c/api/group/update", form)
}

// webPostForm posts application/x-www-form-urlencoded data with the bare
// Authorization style used by the web/app group. Uses a longer timeout than
// the default client: tree-reordering (move/another) can be slow server-side,
// and a timed-out request may still have been applied.
func (c *Client) webPostForm(path string, form url.Values) (json.RawMessage, error) {
	req, err := http.NewRequest("POST", c.baseURL+path, strings.NewReader(form.Encode()))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("Authorization", c.token) // bare token — was missing, caused -1006 on ALL form endpoints
	req.Header.Set("User-Agent", "Cubox/8.3.1 (com.linnk.Linnk; build:668; macOS(Catalyst) 27.0.0) Alamofire/5.10.2")
	req.Header.Set("Accept", "*/*")
	c.throttle()
	slow := &http.Client{Timeout: 120 * time.Second}
	resp, err := slow.Do(req)
	if err != nil {
		return nil, fmt.Errorf("request failed: %w", err)
	}
	defer resp.Body.Close()

	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("reading response: %w", err)
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("HTTP %d: %s", resp.StatusCode, string(data))
	}
	var apiResp APIResponse
	if err := json.Unmarshal(data, &apiResp); err != nil {
		return nil, fmt.Errorf("parsing response: %w", err)
	}
	if apiResp.Code != 200 {
		return nil, fmt.Errorf("API error %d: %s", apiResp.Code, apiResp.Message)
	}
	return apiResp.Data, nil
}

// WebMoveFolderCardsOut moves any remaining cards of a folder to
// Uncategorized and deletes the folder, via
// POST /c/api/group/moveSearchEnginesOut/{id}. This mirrors the Cubox app's
// "move cards to Uncategorized" delete option and never loses cards.
func (c *Client) WebMoveFolderCardsOut(id string) (json.RawMessage, error) {
	return c.webRequest("POST", "/c/api/group/moveSearchEnginesOut/"+id, nil)
}

// WebDeleteFolder hard-deletes a folder via POST /c/api/group/delete/{id}.
// Prefer WebMoveFolderCardsOut unless you know the folder is empty.
func (c *Client) WebDeleteFolder(id string) (json.RawMessage, error) {
	return c.webRequest("POST", "/c/api/group/delete/"+id, nil)
}

// WebArchiveFolder archives or unarchives a folder via POST /c/api/group/update.
func (c *Client) WebArchiveFolder(id string, archive bool) (json.RawMessage, error) {
	form := url.Values{"groupId": {id}, "archiving": {fmt.Sprintf("%v", archive)}}
	return c.webPostForm("/c/api/group/update", form)
}

// WebGetRaw performs a bare-auth GET and returns the parsed {code,message,data}
// envelope. Useful for endpoints whose payload shape varies.
func (c *Client) WebGetRaw(path string) (json.RawMessage, error) {
	req, err := http.NewRequest("GET", c.baseURL+path, nil)
	if err != nil {
		return nil, err
	}
	return c.doRequestAuth(req, true)
}

// WebPostRaw performs a bare-auth POST with a pre-built JSON body.
func (c *Client) WebPostRaw(path string, body interface{}) (json.RawMessage, error) {
	return c.webRequest("POST", path, body)
}

// WebPostMultipart posts multipart/form-data with the bare auth style
// (used by the reading-list endpoints).
func (c *Client) WebPostMultipart(path string, fields map[string]string) (json.RawMessage, error) {
	var buf bytes.Buffer
	w := multipart.NewWriter(&buf)
	keys := make([]string, 0, len(fields))
	for k := range fields {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		if err := w.WriteField(k, fields[k]); err != nil {
			return nil, err
		}
	}
	if err := w.Close(); err != nil {
		return nil, err
	}
	req, err := http.NewRequest("POST", c.baseURL+path, &buf)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", w.FormDataContentType())
	return c.doRequestAuth(req, true)
}

// ---- Recycle bin (web group) ----

// WebRecycleList lists cards in the recycle bin.
func (c *Client) WebRecycleList(page int) (json.RawMessage, error) {
	return c.WebGetRaw(fmt.Sprintf("/c/api/norm/card/recycle/list?page=%d", page))
}

// webSearchEngineIDs encodes card ids the way the recycle endpoints expect:
// a JSON-stringified array of {userSearchEngineID} objects.
func webSearchEngineIDs(ids []string) string {
	type se struct {
		UserSearchEngineID string `json:"userSearchEngineID"`
	}
	arr := make([]se, 0, len(ids))
	for _, id := range ids {
		arr = append(arr, se{UserSearchEngineID: id})
	}
	b, _ := json.Marshal(arr)
	return string(b)
}

// WebRecycleRecover restores cards from the recycle bin.
func (c *Client) WebRecycleRecover(ids []string) (json.RawMessage, error) {
	return c.webPostForm("/c/api/search_engines/recycle/recover",
		url.Values{"searchEngines": {webSearchEngineIDs(ids)}})
}

// WebRecycleClean permanently removes cards from the recycle bin.
func (c *Client) WebRecycleClean(ids []string) (json.RawMessage, error) {
	return c.webPostForm("/c/api/search_engines/recycle/clean",
		url.Values{"searchEngines": {webSearchEngineIDs(ids)}})
}

// WebMarksDelete deletes highlights via POST /c/api/marks/delete.
func (c *Client) WebMarksDelete(ids []string) (json.RawMessage, error) {
	return c.webPostForm("/c/api/marks/delete", url.Values{"ids": {strings.Join(ids, ",")}})
}

// WebMarksColor updates highlight colors via POST /c/api/marks/color/update.
func (c *Client) WebMarksColor(ids []string, color int) (json.RawMessage, error) {
	return c.webPostForm("/c/api/marks/color/update",
		url.Values{"ids": {strings.Join(ids, ",")}, "colorType": {fmt.Sprintf("%d", color)}})
}

// WebMarksExport exports highlights via POST /c/api/norm/marks/export.
// Either slice may be empty (the field is omitted then).
func (c *Client) WebMarksExport(cardIDs, markIDs []string) (json.RawMessage, error) {
	form := url.Values{}
	if len(cardIDs) > 0 {
		form.Set("cardIds", strings.Join(cardIDs, ","))
	}
	if len(markIDs) > 0 {
		form.Set("markIds", strings.Join(markIDs, ","))
	}
	return c.webPostForm("/c/api/norm/marks/export", form)
}

// WebMarksExportText exports highlights as plain text.
func (c *Client) WebMarksExportText(cardIDs, markIDs []string) (json.RawMessage, error) {
	form := url.Values{}
	if len(cardIDs) > 0 {
		form.Set("cardIds", strings.Join(cardIDs, ","))
	}
	if len(markIDs) > 0 {
		form.Set("markIds", strings.Join(markIDs, ","))
	}
	return c.webPostForm("/c/api/norm/marks/export/text", form)
}

// WebMarkCount returns the total mark count.
func (c *Client) WebMarkCount() (json.RawMessage, error) {
	return c.WebGetRaw("/c/api/mark/count")
}

// ---- Batch card operations (web group, form with comma-joined cardIds) ----

// WebCardsStar stars/unstars cards in batch.
func (c *Client) WebCardsStar(ids []string, star bool) (json.RawMessage, error) {
	return c.webPostForm("/c/api/norm/cards/updateToStarTarget",
		url.Values{"cardIds": {strings.Join(ids, ",")}, "starTarget": {fmt.Sprintf("%v", star)}})
}

// WebCardsRead marks cards as read in batch.
func (c *Client) WebCardsRead(ids []string) (json.RawMessage, error) {
	return c.webPostForm("/c/api/norm/card/read", url.Values{"cardIds": {strings.Join(ids, ",")}})
}

// WebCardsMove moves cards to a folder in batch.
func (c *Client) WebCardsMove(ids []string, groupID string) (json.RawMessage, error) {
	return c.webPostForm("/c/api/norm/cards/moveToGroup/"+groupID,
		url.Values{"groupId": {groupID}, "cardIds": {strings.Join(ids, ",")}})
}

// WebCardsAddTagsByName adds tags (by name) to cards in batch, optionally
// removing tag ids from them.
func (c *Client) WebCardsAddTagsByName(ids []string, addNames []string, deleteTagIDs []string) (json.RawMessage, error) {
	addJSON := "[]"
	if len(addNames) > 0 {
		b, _ := json.Marshal(addNames)
		addJSON = string(b)
	}
	form := url.Values{
		"cardIds":           {strings.Join(ids, ",")},
		"addLinkedTagNames": {addJSON},
	}
	if len(deleteTagIDs) > 0 {
		form.Set("deleteTagIds", strings.Join(deleteTagIDs, ","))
	}
	return c.webPostForm("/c/api/norm/cards/updateTagsForName", form)
}

// ---- Tags (web group) ----

// WebMoveTag moves an existing tag without changing its ID or card links.
// The fields match the Cubox web app's /tag/sort request.
func (c *Client) WebMoveTag(id, parentID string) (json.RawMessage, error) {
	form := url.Values{"sourceTagId": {id}, "targetParentId": {parentID}}
	return c.webPostForm("/c/api/tag/sort", form)
}

// WebTagNew creates a tag via POST /c/api/v2/tag/new.
// parentID may be empty for a root-level tag. linkedName is the leaf name.
func (c *Client) WebTagNew(linkedName, parentID string) (json.RawMessage, error) {
	form := url.Values{"linkedName": {linkedName}}
	if parentID != "" {
		form.Set("parentId", parentID)
	}
	return c.webPostForm("/c/api/v2/tag/new", form)
}

// ---- Reading lists: extra operations ----

// WebReadingListUpdate updates a reading list title/intro (multipart).
func (c *Client) WebReadingListUpdate(id, title, intro string) (json.RawMessage, error) {
	f := map[string]string{"id": id}
	if title != "" {
		f["title"] = title
	}
	if intro != "" {
		f["intro"] = intro
	}
	return c.WebPostMultipart("/c/api/norm/reading-list/update", f)
}

// WebReadingListPublish publishes/unpublishes a reading list (multipart).
func (c *Client) WebReadingListPublish(id string, published bool) (json.RawMessage, error) {
	return c.WebPostMultipart("/c/api/norm/reading-list/publish",
		map[string]string{"id": id, "published": fmt.Sprintf("%v", published)})
}

// WebReadingListCollect collects a card into a reading list (multipart).
func (c *Client) WebReadingListCollect(listID, cardID string) (json.RawMessage, error) {
	return c.WebPostMultipart("/c/api/norm/reading-list/collect",
		map[string]string{"id": listID, "cardId": cardID})
}

// WebReadingListCollectAll collects all listed cards at once (multipart).
func (c *Client) WebReadingListCollectAll(listID string) (json.RawMessage, error) {
	return c.WebPostMultipart("/c/api/norm/reading-list/collect/all",
		map[string]string{"id": listID})
}

// WebReadingListCards lists the cards of a reading list.
func (c *Client) WebReadingListCards(id string, page, size int) (json.RawMessage, error) {
	return c.WebGetRaw(fmt.Sprintf("/c/api/norm/reading-list/%s/cards?page=%d&size=%d",
		url.QueryEscape(id), page, size))
}

// WebListsItemsSort reorders items of a reading list (multipart).
func (c *Client) WebListsItemsSort(listID string, cardIDs []string) (json.RawMessage, error) {
	return c.WebPostMultipart("/c/api/norm/lists/items/sort",
		map[string]string{"listId": listID, "cardIds": strings.Join(cardIDs, ",")})
}

// WebListsCheck reports which reading lists contain the given cards.
func (c *Client) WebListsCheck(cardIDs []string) (json.RawMessage, error) {
	return c.WebPostMultipart("/c/api/norm/lists/items/check-list",
		map[string]string{"cardIds": strings.Join(cardIDs, ",")})
}

// ---- Account extras ----

// WebMailSettings returns the Mail Drop (email-in) settings.
func (c *Client) WebMailSettings() (json.RawMessage, error) {
	return c.WebGetRaw("/c/api/v2/user/mail/settings/info?tagDetail=true")
}

// WebInsightState returns the AI insight generation state of a card.
func (c *Client) WebInsightState(cardID string) (json.RawMessage, error) {
	return c.WebGetRaw("/c/api/card/insight/state/" + cardID)
}

// WebInsightMoreQAs returns follow-up Q&As of a card's insight.
func (c *Client) WebInsightMoreQAs(cardID string) (json.RawMessage, error) {
	return c.WebGetRaw("/c/api/card/insight/moreQas/" + cardID)
}

// ---- Import (web group) ----

// WebBookmarkImport uploads a bookmarks export file (HTML/Netscape) through
// the official import task pipeline. Experimental: the multipart file field
// name is inferred from the app ("uploadFile").
func (c *Client) WebBookmarkImport(filePath string) (json.RawMessage, error) {
	data, err := os.ReadFile(filePath)
	if err != nil {
		return nil, err
	}
	var buf bytes.Buffer
	w := multipart.NewWriter(&buf)
	part, err := w.CreateFormFile("uploadFile", filepath.Base(filePath))
	if err != nil {
		return nil, err
	}
	if _, err := part.Write(data); err != nil {
		return nil, err
	}
	if err := w.Close(); err != nil {
		return nil, err
	}
	req, err := http.NewRequest("POST", c.baseURL+"/c/api/v2/bookmark/import", &buf)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", w.FormDataContentType())
	req.Header.Set("User-Agent", "Cubox/8.3.1 (com.linnk.Linnk; build:668; macOS(Catalyst) 27.0.0) Alamofire/5.10.2")
	return c.doRequestAuth(req, true)
}

// WebImportProgress returns the progress of the latest import task.
func (c *Client) WebImportProgress() (json.RawMessage, error) {
	return c.WebGetRaw("/c/api/importTask/progress")
}

// ---- Marks (highlights, web group) ----

// WebMarksList lists highlights via GET /c/api/norm/mark/list.
func (c *Client) WebMarksList(page int, keyword string) (json.RawMessage, error) {
	q := fmt.Sprintf("page=%d", page)
	if keyword != "" {
		q += "&keyword=" + url.QueryEscape(keyword)
	}
	return c.WebGetRaw("/c/api/norm/mark/list?" + q)
}

// ---- Reading lists (web group, multipart) ----

// WebReadingLists lists reading lists via GET /c/api/norm/reading-list/my.
func (c *Client) WebReadingLists() (json.RawMessage, error) {
	return c.WebGetRaw("/c/api/norm/reading-list/my")
}

// WebReadingListAddItem adds a card to a reading list.
func (c *Client) WebReadingListAddItem(listID, cardID string, includeHighlight, includeNote bool) (json.RawMessage, error) {
	f := map[string]string{"listId": listID, "cardId": cardID,
		"includeHighlight": fmt.Sprintf("%v", includeHighlight), "includeNote": fmt.Sprintf("%v", includeNote)}
	return c.WebPostMultipart("/c/api/norm/lists/items/add", f)
}

// WebReadingListRemoveItem removes a card from a reading list.
func (c *Client) WebReadingListRemoveItem(listID, cardID string) (json.RawMessage, error) {
	return c.WebPostMultipart("/c/api/norm/lists/items/remove",
		map[string]string{"listId": listID, "cardId": cardID})
}

// WebReadingListCreate creates a reading list (multipart: title/intro).
func (c *Client) WebReadingListCreate(title, intro string) (json.RawMessage, error) {
	f := map[string]string{"title": title}
	if intro != "" {
		f["intro"] = intro
	}
	return c.WebPostMultipart("/c/api/norm/reading-list/new", f)
}

// WebReadingListDelete deletes a reading list via DELETE /c/api/norm/reading-list/{id}.
func (c *Client) WebReadingListDelete(id string) (json.RawMessage, error) {
	req, err := http.NewRequest("DELETE", c.baseURL+"/c/api/norm/reading-list/"+id, nil)
	if err != nil {
		return nil, err
	}
	return c.doRequestAuth(req, true)
}

// WebSettingsUpdate writes reading settings back (experimental: the payload
// must be the full settings object as returned by GET /c/api/settings/read).
// The web group parses form-encoded bodies, so values are stringified.
func (c *Client) WebSettingsUpdate(body map[string]interface{}) (json.RawMessage, error) {
	form := url.Values{}
	for k, v := range body {
		form.Set(k, fmt.Sprintf("%v", v))
	}
	return c.webPostForm("/c/api/settings/read/update", form)
}

// WebCardsExportMail requests an async export of the given cards, delivered
// by email. Form-urlencoded: cardIds (comma-joined) + email.
func (c *Client) WebCardsExportMail(ids []string, email string) (json.RawMessage, error) {
	form := url.Values{"cardIds": {strings.Join(ids, ",")}, "email": {email}}
	return c.webPostForm("/c/api/norm/cards/export/async", form)
}

// WebMoveFolderAnother moves/reorders folders. fromJSON/toJSON are
// JSON-stringified arrays of {groupId, parentGroupId} snapshots — the same
// shape the web app submits on drag & drop. fromGroups may be "" for a
// same-parent reorder. The endpoint expects form-urlencoded input.
func (c *Client) WebMoveFolderAnother(fromJSON, toJSON string) (json.RawMessage, error) {
	form := url.Values{"toGroups": {toJSON}}
	if fromJSON != "" {
		form.Set("fromGroups", fromJSON)
	}
	return c.webPostForm("/c/api/group/move/another", form)
}

// WebInsightGenerateStream triggers AI insight generation for a card and
// streams the SSE response line by line. Uses a dedicated client without the
// 30s timeout because generation can run long.
func (c *Client) WebInsightGenerateStream(cardID string, onLine func(string)) error {
	req, err := http.NewRequest("GET",
		c.baseURL+"/c/api/card/insight/generate/stream?cardId="+url.QueryEscape(cardID), nil)
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", c.token) // bare, web/app group
	req.Header.Set("User-Agent", "Cubox/8.3.1 (com.linnk.Linnk; build:668; macOS(Catalyst) 27.0.0) Alamofire/5.10.2")
	req.Header.Set("Accept", "text/event-stream")
	streamClient := &http.Client{}
	resp, err := streamClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	scanner := bufio.NewScanner(resp.Body)
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	for scanner.Scan() {
		if line := scanner.Text(); line != "" {
			onLine(line)
		}
	}
	return scanner.Err()
}

// WebAIAsk asks the Cubox AI assistant a question and streams the answer.
//
// POST /c/api/ai/ask, form-urlencoded (question, optional context for
// card-scoped Q&A, optional collectId), SSE response in OpenAI delta format
// (data: {"choices":[{"delta":{"content":"..."}}]}, terminated by [DONE]).
// context mirrors the in-card Q&A; collectId mirrors the assistant panel.
func (c *Client) WebAIAsk(question, context, collectID string, onDelta func(string)) error {
	form := url.Values{"question": {question}}
	if context != "" {
		form.Set("context", context)
	}
	if collectID != "" {
		form.Set("collectId", collectID)
	}
	req, err := http.NewRequest("POST", c.baseURL+"/c/api/ai/ask",
		strings.NewReader(form.Encode()))
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", c.token) // bare, web/app group
	req.Header.Set("User-Agent", "Cubox/8.3.1 (com.linnk.Linnk; build:668; macOS(Catalyst) 27.0.0) Alamofire/5.10.2")
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("Accept", "*/*")
	streamClient := &http.Client{}
	resp, err := streamClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	scanner := bufio.NewScanner(resp.Body)
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || !strings.HasPrefix(line, "data:") {
			continue
		}
		payload := strings.TrimSpace(strings.TrimPrefix(line, "data:"))
		if payload == "" {
			continue
		}
		if payload == "[DONE]" {
			return nil
		}
		var chunk struct {
			Choices []struct {
				Delta struct {
					Content string `json:"content"`
				} `json:"delta"`
			} `json:"choices"`
		}
		if err := json.Unmarshal([]byte(payload), &chunk); err != nil {
			onDelta(payload) // non-delta payload: pass through
			continue
		}
		for _, ch := range chunk.Choices {
			if ch.Delta.Content != "" {
				onDelta(ch.Delta.Content)
			}
		}
	}
	return scanner.Err()
}
