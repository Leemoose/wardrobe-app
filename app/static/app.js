/* ========================================
   Wardrobe PWA - Main Application
   ======================================== */

// ========================================
// State
// ========================================

const state = {
    currentTab: 'today',
    settings: null,
    items: [],
    outfits: [],
    dirtyItems: [],
    pendingOutfits: [],
    suggestData: null,
    stats: null,
    gapsData: null,
    wearHistory: [],
    calendarYear: new Date().getFullYear(),
    calendarMonth: new Date().getMonth(),
    closetFilters: {
        category: '',
        status: '',
        search: '',
        lifecycle: 'active'
    },
    outfitFilters: {
        season: '',
        vibe: '',
        availableOnly: false
    },
    selectedVibe: 'any',
    includeRecent: false,
    laundrySelectMode: false,
    laundrySelected: new Set(),
    aiGenerateCount: 5,
    aiGenerating: false,
    aiEngine: 'auto',  // 'auto' | 'anthropic' | 'openai' | 'local'
    aiStatus: null,    // cached GET /ai/status ({anthropic, openai, ...})
    closetSubview: 'closet',  // 'closet' | 'wishlist' | 'scents'
    wishlist: [],
    scents: [],
    scentFilters: {
        status: '',
        search: '',
        sort: 'rating'
    },
    scentSuggestion: null,  // cached GET /scents/suggest for the Today card
    activeTrip: null,  // {id, name, destination, start_date, end_date, item_ids: [...]}
    trips: [],
    tripDetail: null,
    closetShowAll: false,
    outfitShowAll: false,
    // itemId -> timestamp. Set after a photo rotate: the URL is unchanged but
    // the pixels are not, so every <img> for that item needs a cache-bust.
    photoBust: {}
};

// Fiber suggestions for the composition editor (shared <datalist>)
const FIBER_OPTIONS = [
    'cotton', 'elastane', 'polyester', 'polyamide', 'nylon', 'wool', 'merino',
    'cashmere', 'silk', 'linen', 'viscose', 'modal', 'lyocell', 'spandex',
    'acrylic', 'rayon', 'leather', 'suede', 'down', 'rubber'
];

const CARE_METHOD_OPTIONS = [
    'Machine wash, tumble dry',
    'Machine wash, line dry',
    'Machine wash cold, dry flat',
    'Hand wash, dry flat',
    'Dry clean',
    'Dry clean only',
    'Spot clean / wipe down'
];

// ========================================
// API Helper
// ========================================

// Today's date in the *client's* local timezone as YYYY-MM-DD.
// (toISOString() is UTC and rolls over at 7/8pm ET — wrong for wear logging.)
function localToday() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

async function api(path, options = {}) {
    const url = '/api' + path;
    const config = {
        headers: {},
        ...options
    };

    if (options.body && !(options.body instanceof FormData)) {
        config.headers['Content-Type'] = 'application/json';
        config.body = JSON.stringify(options.body);
    }

    const res = await fetch(url, config);

    if (!res.ok) {
        let detail = `Request failed: ${res.status}`;
        try {
            const data = await res.json();
            if (data.detail) {
                detail = data.detail;
            }
        } catch (e) {
            // ignore parse errors
        }
        throw new Error(detail);
    }

    // Any trip mutation invalidates the active-trip cache
    const method = (config.method || 'GET').toUpperCase();
    if (method !== 'GET' && path.startsWith('/trips')) {
        invalidateTripCache();
    }

    return res.json();
}

// ========================================
// Toast Helper
// ========================================

function toast(message, type = 'success') {
    const container = document.getElementById('toast-container');
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = message;
    container.appendChild(el);

    setTimeout(() => {
        el.remove();
    }, 3000);
}

// ========================================
// Full-Screen Image Viewer
// ========================================

function openFullScreenImage(src) {
    const viewer = document.createElement('div');
    viewer.className = 'fullscreen-viewer';
    viewer.innerHTML = `<img src="${escapeHtml(src)}" alt="Full view">`;
    viewer.addEventListener('click', () => viewer.remove());
    document.body.appendChild(viewer);
}

// ========================================
// HTML Escape
// ========================================

function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

// ========================================
// Utility Functions
// ========================================

function formatDate(dateStr) {
    if (!dateStr) return 'never';
    // A bare YYYY-MM-DD is parsed as UTC midnight, which renders as the day
    // before anywhere west of Greenwich — a wear logged today came back as
    // yesterday. Build those as a local date instead. (Same reasoning as
    // localToday(); values that carry a time are left to the normal parser.)
    const parts = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(dateStr).trim());
    const d = parts
        ? new Date(Number(parts[1]), Number(parts[2]) - 1, Number(parts[3]))
        : new Date(dateStr);
    return d.toLocaleDateString();
}

function formatCurrency(value) {
    if (!value || value <= 0) return '-';
    return '$' + value.toFixed(2);
}

// Photo rotation changes the bytes behind an unchanged URL, so the browser
// would happily serve the stale (un-rotated) image. Append a per-item token.
function bustedPhotoUrl(url, itemId) {
    const t = state.photoBust[itemId];
    if (!url || !t) return url;
    return url + (url.includes('?') ? '&' : '?') + 't=' + t;
}

function getItemThumbHtml(item) {
    if (item.photo) {
        const src = bustedPhotoUrl(item.photo_thumb || item.photo, item.id);
        return `<img src="${escapeHtml(src)}" alt="${escapeHtml(item.name)}" loading="lazy">`;
    }
    return `<span class="placeholder">#${escapeHtml(item.number)}</span>`;
}

// Distinct non-empty values of a field across the closet, case-preserving
// (first spelling wins), sorted — used to populate <datalist> combos.
function existingItemValues(key) {
    const seen = new Map();
    (state.items || []).forEach(i => {
        const raw = i && i[key] != null ? String(i[key]).trim() : '';
        if (!raw) return;
        const k = raw.toLowerCase();
        if (!seen.has(k)) seen.set(k, raw);
    });
    return Array.from(seen.values()).sort((a, b) => a.localeCompare(b));
}

function datalistOptionsHtml(values) {
    return values.map(v => `<option value="${escapeHtml(v)}"></option>`).join('');
}

function renderTagChips(tags, small = false) {
    if (!tags || tags.length === 0) return '';
    return tags.map(t => `<span class="chip ${small ? 'small' : ''}">${escapeHtml(t)}</span>`).join('');
}

// ========================================
// Modal Functions
// ========================================

function openModal(html, full = false) {
    const overlay = document.getElementById('modal-overlay');
    const container = document.getElementById('modal-container');

    container.innerHTML = `<div class="modal ${full ? 'full' : ''}">${html}</div>`;
    overlay.classList.remove('hidden');
    container.classList.remove('hidden');
}

function closeModal() {
    document.getElementById('modal-overlay').classList.add('hidden');
    document.getElementById('modal-container').classList.add('hidden');
}

document.getElementById('modal-overlay').addEventListener('click', closeModal);

// ========================================
// Router / Tab Navigation
// ========================================

function initTabs() {
    const tabBar = document.getElementById('tab-bar');
    tabBar.addEventListener('click', (e) => {
        const btn = e.target.closest('.tab-btn');
        if (!btn) return;
        const tab = btn.dataset.tab;
        navigateTo(tab);
    });
}

function navigateTo(tab) {
    state.currentTab = tab;
    updateActiveTab();
    renderCurrentView();
}

function updateActiveTab() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === state.currentTab);
    });
}

function renderCurrentView() {
    const main = document.getElementById('main-content');

    switch (state.currentTab) {
        case 'today':
            renderTodayView(main);
            break;
        case 'closet':
            renderClosetView(main);
            break;
        case 'outfits':
            renderOutfitsView(main);
            break;
        case 'laundry':
            renderLaundryView(main);
            break;
        case 'stats':
            renderStatsView(main);
            break;
        case 'trips':
            renderTripsView(main);
            break;
        case 'care':
            renderCareView(main);
            break;
        case 'settings':
            renderSettingsView(main);
            break;
    }
}

// ========================================
// VACATION BANNER
// ========================================

function renderVacationBanner() {
    if (!state.activeTrip) return '';
    const trip = state.activeTrip;
    const dest = trip.destination ? ` (${escapeHtml(trip.destination)})` : '';
    return `
        <div class="vacation-banner">
            <div class="vacation-banner-text">Vacation mode: ${escapeHtml(trip.name)}${dest}</div>
            <button class="btn btn-sm" id="vacation-end-btn">End</button>
        </div>
    `;
}

function setupVacationBanner(container) {
    const btn = container.querySelector('#vacation-end-btn');
    if (!btn) return;
    btn.addEventListener('click', async () => {
        if (!confirm('End vacation mode? Today, Closet, and Outfits will show all items again.')) return;
        try {
            await api(`/trips/${state.activeTrip.id}/deactivate`, { method: 'POST' });
            state.activeTrip = null;
            toast('Vacation mode ended');
            renderCurrentView();
        } catch (err) {
            toast(err.message, 'error');
        }
    });
}

// ========================================
// TODAY VIEW
// ========================================

async function renderTodayView(container) {
    container.innerHTML = '<div class="flex-center"><div class="spinner"></div></div>';

    try {
        await loadSettings();
        await loadActiveTrip();
        const vibeParam = state.selectedVibe === 'any' ? '' : encodeURIComponent(state.selectedVibe);
        const recentParam = state.includeRecent ? 'true' : 'false';
        state.suggestData = await api(`/suggest?vibe=${vibeParam}&include_recent=${recentParam}`);
    } catch (err) {
        container.innerHTML = `<div class="empty-state"><div class="empty-state-text">Error loading: ${escapeHtml(err.message)}</div></div>`;
        return;
    }

    // Scent pick is a bonus on this screen, not the point of it — a failure
    // here must not cost the user their outfit suggestions.
    try {
        const period = new Date().getHours() >= 17 || new Date().getHours() < 5 ? 'night' : 'day';
        const occasion = state.selectedVibe === 'any' ? '' : encodeURIComponent(state.selectedVibe);
        state.scentSuggestion = await api(`/scents/suggest?time_of_day=${period}&occasion=${occasion}&limit=3`);
    } catch (err) {
        state.scentSuggestion = null;
    }

    const weather = state.suggestData.weather;
    const outfits = state.suggestData.outfits || [];
    const hiddenRecent = state.suggestData.hidden_recent || 0;
    const hiddenTrip = state.suggestData.hidden_trip || 0;
    const hiddenRest = state.suggestData.hidden_rest || 0;
    const noRepeatDays = state.settings?.no_repeat_days || 0;

    let weatherHtml = '';
    if (weather && !weather.error) {
        weatherHtml = `
            <div class="weather-card">
                <div class="weather-location">${escapeHtml(weather.location_name)}</div>
                <div class="weather-temp">${Math.round(weather.temp_f)}&deg;F</div>
                <div class="weather-feels">Feels like ${Math.round(weather.feels_like_f)}&deg;F</div>
                <div class="weather-details">
                    <span>H: ${Math.round(weather.high_f)}&deg;</span>
                    <span>L: ${Math.round(weather.low_f)}&deg;</span>
                    <span>${weather.precip_prob}% precip</span>
                </div>
                <div class="weather-description">${escapeHtml(weather.description)}</div>
                <div class="chip-row">
                    <span class="chip small active">${escapeHtml(weather.season)}</span>
                </div>
            </div>
        `;
    } else if (weather && weather.error) {
        weatherHtml = `
            <div class="weather-card">
                <div class="weather-error">${escapeHtml(weather.error)}</div>
            </div>
        `;
    } else {
        weatherHtml = `
            <div class="weather-card">
                <div class="weather-error">Weather unavailable - check Settings</div>
            </div>
        `;
    }

    const vibes = ['any', ...(state.settings?.vibe_tags || [])];
    const vibeChipsHtml = vibes.map(v =>
        `<span class="chip ${state.selectedVibe === v ? 'active' : ''}" data-vibe="${escapeHtml(v)}">${escapeHtml(v)}</span>`
    ).join('');

    let outfitsHtml = '';
    if (outfits.length === 0) {
        outfitsHtml = `
            <div class="empty-state">
                <div class="empty-state-text">Everything's dirty or no outfits match - check Laundry or make outfits</div>
            </div>
        `;
    } else {
        outfitsHtml = outfits.map(outfit => renderOutfitCard(outfit, true)).join('');
    }

    // Hidden recent outfits line
    let hiddenRecentHtml = '';
    if (hiddenRecent > 0 && !state.includeRecent) {
        hiddenRecentHtml = `
            <div class="hidden-recent-line" id="hidden-recent-toggle">
                ${hiddenRecent} outfits hidden - worn in the last ${noRepeatDays} days · <span class="link-text">Show anyway</span>
            </div>
        `;
    } else if (state.includeRecent && hiddenRecent > 0) {
        hiddenRecentHtml = `
            <div class="hidden-recent-line" id="hidden-recent-toggle">
                Showing all outfits · <span class="link-text">Hide recent</span>
            </div>
        `;
    }

    // Hidden resting-items line (categories with rest days, e.g. shoes)
    let hiddenRestHtml = '';
    if (hiddenRest > 0 && !state.includeRecent) {
        hiddenRestHtml = `
            <div class="hidden-recent-line" id="hidden-rest-toggle">
                ${hiddenRest} outfits hidden - items resting between wears · <span class="link-text">Show anyway</span>
            </div>
        `;
    }

    // Hidden trip outfits note
    let hiddenTripHtml = '';
    if (hiddenTrip > 0) {
        hiddenTripHtml = `<div class="inline-note">${hiddenTrip} outfits hidden (not fully packed)</div>`;
    }

    container.innerHTML = `
        ${renderVacationBanner()}
        ${weatherHtml}
        <div class="chip-row scrollable" id="vibe-picker">${vibeChipsHtml}</div>
        ${renderScentOfDayCard()}
        <div id="today-outfits">${outfitsHtml}</div>
        ${hiddenRecentHtml}
        ${hiddenRestHtml}
        ${hiddenTripHtml}
        <button class="btn btn-secondary btn-block mt-md" id="wore-something-else-btn">Wore something else</button>
    `;

    setupVacationBanner(container);

    // Vibe picker
    document.getElementById('vibe-picker').addEventListener('click', async (e) => {
        const chip = e.target.closest('.chip');
        if (!chip) return;
        state.selectedVibe = chip.dataset.vibe;
        renderTodayView(container);
    });

    // Hidden recent toggle
    document.getElementById('hidden-recent-toggle')?.addEventListener('click', () => {
        state.includeRecent = !state.includeRecent;
        renderTodayView(container);
    });

    document.getElementById('hidden-rest-toggle')?.addEventListener('click', () => {
        state.includeRecent = true;
        renderTodayView(container);
    });

    // Wore something else button
    document.getElementById('wore-something-else-btn').addEventListener('click', () => {
        openWoreElseModal();
    });

    // Wear buttons
    container.querySelectorAll('.wear-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const outfitId = parseInt(btn.dataset.outfitId);
            const outfit = outfits.find(o => o.id === outfitId);
            if (outfit) openWearDialog(outfit);
        });
    });

    setupScentOfDayCard(container);
}

// Today's scent pick. Renders nothing at all when there are no owned bottles —
// an empty prompt on the main screen would be noise for someone who only uses
// the journal to record things tried in shops.
function renderScentOfDayCard() {
    const data = state.scentSuggestion;
    if (!data || !data.owned_count || !data.scents || data.scents.length === 0) return '';

    const pick = data.scents[0];
    const reason = (pick.reasons || []).slice(0, 2).join(' · ');
    const subtitle = scentSubtitle(pick);

    const relaxedNote = data.relaxed
        ? `<div class="scent-today-note">Nothing tagged for ${escapeHtml(data.season)} — showing your closest match</div>`
        : '';

    return `
        <div class="scent-today-card" data-scent-id="${pick.id}">
            <div class="scent-today-label">Scent for today</div>
            <div class="scent-today-body">
                <div class="scent-today-thumb">${scentThumbHtml(pick)}</div>
                <div class="scent-today-info">
                    <div class="scent-today-name">${escapeHtml(pick.name)}</div>
                    ${subtitle ? `<div class="scent-subtitle">${escapeHtml(subtitle)}</div>` : ''}
                    ${starsHtml(pick.rating, 'small')}
                    ${reason ? `<div class="scent-today-reason">${escapeHtml(reason)}</div>` : ''}
                </div>
            </div>
            ${relaxedNote}
            <div class="scent-today-actions">
                <button class="btn btn-sm btn-outline" id="scent-today-open">Details</button>
                <button class="btn btn-sm btn-primary" id="scent-today-wear">Wore this</button>
            </div>
        </div>
    `;
}

function setupScentOfDayCard(container) {
    const card = container.querySelector('.scent-today-card');
    if (!card) return;
    const scentId = parseInt(card.dataset.scentId);

    container.querySelector('#scent-today-open')?.addEventListener('click', () => {
        openScentDetail(scentId);
    });

    container.querySelector('#scent-today-wear')?.addEventListener('click', async () => {
        const sprays = state.settings?.scent_rules?.default_sprays ?? 2;
        try {
            await api(`/scents/${scentId}/notes`, {
                method: 'POST',
                body: { sprays, date: localToday(), note: '' }
            });
            state.scentSuggestion = null;
            toast('Logged — add a note any time from Scents');
            renderTodayView(container);
        } catch (err) {
            toast(err.message, 'error');
        }
    });
}

function renderOutfitCard(outfit, showWearBtn = false) {
    const thumbsHtml = (outfit.items || []).map(item => `
        <div class="item-thumb">${getItemThumbHtml(item)}</div>
    `).join('');

    const badges = [];
    if (outfit.source === 'ai') {
        badges.push('<span class="badge ai">AI</span>');
    }
    if (outfit.available !== undefined) {
        badges.push(outfit.available
            ? '<span class="badge ready">Ready</span>'
            : '<span class="badge missing">Missing pieces</span>'
        );
    }

    // Render warnings as amber badge lines
    const warnings = outfit.warnings || [];
    const warningsHtml = warnings.map(w => `
        <div class="outfit-warning"><span class="warning-icon">!</span> ${escapeHtml(w)}</div>
    `).join('');

    // Outfit preview image: photo > collage > thumbnails fallback
    let previewHtml = '';
    if (outfit.photo) {
        previewHtml = `<div class="outfit-preview"><img src="${escapeHtml(outfit.photo)}" alt="${escapeHtml(outfit.name)}" class="outfit-preview-img" loading="lazy"></div>`;
    } else if (outfit.has_collage) {
        // Render the thumbnail fallback alongside the collage and swap on error.
        // Interpolating thumbsHtml into the onerror attribute breaks the markup:
        // it carries double quotes, which close the attribute early and spill the
        // rest of the string into the document as raw text.
        previewHtml = `<div class="outfit-preview"><img src="/api/outfits/${outfit.id}/collage" alt="${escapeHtml(outfit.name)}" class="outfit-preview-img" loading="lazy" onerror="this.hidden=true;this.nextElementSibling.hidden=false;"><div class="outfit-thumbnails" hidden>${thumbsHtml}</div></div>`;
    } else {
        previewHtml = `<div class="outfit-thumbnails">${thumbsHtml}</div>`;
    }

    return `
        <div class="outfit-card" data-outfit-id="${outfit.id}">
            <div class="outfit-header">
                <span class="outfit-name">${escapeHtml(outfit.name)}</span>
                <div class="outfit-badges">${badges.join('')}</div>
            </div>
            ${previewHtml}
            <div class="outfit-tags">
                ${renderTagChips(outfit.season_tags, true)}
                ${renderTagChips(outfit.vibe_tags, true)}
            </div>
            ${warningsHtml}
            ${outfit.ai_note ? `<div class="outfit-note">${escapeHtml(outfit.ai_note)}</div>` : ''}
            ${showWearBtn ? `<button class="btn btn-primary btn-block wear-btn" data-outfit-id="${outfit.id}">Wore this</button>` : ''}
        </div>
    `;
}

function openWearDialog(outfit) {
    const items = outfit.items || [];
    const thresholds = state.settings?.dirty_thresholds || {};

    const itemsHtml = items.map(item => {
        const threshold = thresholds[item.category] || 0;
        const wouldBeDirty = threshold > 0 && (item.wears_since_wash + 1) >= threshold;

        return `
            <div class="wear-item">
                <div class="wear-item-info">
                    <div class="wear-item-thumb">${getItemThumbHtml(item)}</div>
                    <span>${escapeHtml(item.name)}</span>
                </div>
                <div class="toggle ${wouldBeDirty ? '' : 'active'}" data-item-id="${item.id}" data-dirty="${wouldBeDirty}"></div>
            </div>
            <div class="text-muted" style="font-size: 12px; margin-top: -8px; margin-bottom: 8px; text-align: right;">
                ${wouldBeDirty ? 'Now dirty' : 'Still clean'}
            </div>
        `;
    }).join('');

    openModal(`
        <div class="modal-header">
            <span class="modal-title">Log Wear: ${escapeHtml(outfit.name)}</span>
            <button class="modal-close" onclick="closeModal()">&times;</button>
        </div>
        <div class="modal-body">
            <p style="margin-bottom: 16px; color: var(--text-secondary);">Mark each item's status after wearing:</p>
            ${itemsHtml}
        </div>
        <div class="modal-footer">
            <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
            <button class="btn btn-primary" id="confirm-wear-btn">Confirm</button>
        </div>
    `);

    // Toggle handlers
    document.querySelectorAll('.wear-item .toggle').forEach(toggle => {
        toggle.addEventListener('click', () => {
            const isDirty = toggle.dataset.dirty === 'true';
            toggle.dataset.dirty = (!isDirty).toString();
            toggle.classList.toggle('active', isDirty);

            const label = toggle.closest('.wear-item').nextElementSibling;
            if (label) {
                label.textContent = isDirty ? 'Still clean' : 'Now dirty';
            }
        });
    });

    // Confirm
    document.getElementById('confirm-wear-btn').addEventListener('click', async () => {
        const itemData = [];
        document.querySelectorAll('.wear-item .toggle').forEach(toggle => {
            itemData.push({
                item_id: parseInt(toggle.dataset.itemId),
                dirty: toggle.dataset.dirty === 'true'
            });
        });

        try {
            const result = await api('/wear', {
                method: 'POST',
                body: {
                    outfit_id: outfit.id,
                    date: localToday(),
                    items: itemData
                }
            });
            // Show photo upload follow-up prompt
            showWearPhotoPrompt(result.event_id, outfit);
        } catch (err) {
            toast(err.message, 'error');
        }
    });
}

function showWearPhotoPrompt(eventId, outfit = null) {
    const hasOutfit = outfit && outfit.id;
    const outfitNeedsPreview = hasOutfit && !outfit.photo;

    openModal(`
        <div class="modal-header">
            <span class="modal-title">Add a photo of the fit?</span>
            <button class="modal-close" onclick="closeModal()">&times;</button>
        </div>
        <div class="modal-body">
            <div class="form-group">
                <div class="file-input-wrapper">
                    <input type="file" class="file-input" accept="image/*" id="wear-photo-input">
                    <div class="file-input-btn">
                        <span>Take or choose photo</span>
                    </div>
                </div>
                <img class="file-preview hidden" id="wear-photo-preview">
            </div>
            ${hasOutfit ? `
            <div class="form-group">
                <label class="toggle-group">
                    <span class="toggle-label">Use as outfit preview</span>
                    <div class="toggle ${outfitNeedsPreview ? 'active' : ''}" id="set-outfit-preview-toggle"></div>
                </label>
            </div>
            ` : ''}
        </div>
        <div class="modal-footer">
            <button class="btn btn-secondary" id="skip-wear-photo-btn">Skip</button>
            <button class="btn btn-primary" id="upload-wear-photo-btn" disabled>Upload</button>
        </div>
    `);

    const photoInput = document.getElementById('wear-photo-input');
    const preview = document.getElementById('wear-photo-preview');
    const uploadBtn = document.getElementById('upload-wear-photo-btn');
    const skipBtn = document.getElementById('skip-wear-photo-btn');
    const previewToggle = document.getElementById('set-outfit-preview-toggle');

    photoInput.addEventListener('change', (e) => {
        if (e.target.files[0]) {
            preview.src = URL.createObjectURL(e.target.files[0]);
            preview.classList.remove('hidden');
            uploadBtn.disabled = false;
        }
    });

    previewToggle?.addEventListener('click', function() {
        this.classList.toggle('active');
    });

    skipBtn.addEventListener('click', () => {
        closeModal();
        toast('Wear logged!');
        renderTodayView(document.getElementById('main-content'));
    });

    uploadBtn.addEventListener('click', async () => {
        const file = photoInput.files[0];
        if (!file) return;

        const setOutfitPreview = previewToggle?.classList.contains('active') || false;
        const formData = new FormData();
        formData.append('file', file);

        try {
            const query = setOutfitPreview ? '?set_outfit_preview=true' : '';
            await api(`/wear/${eventId}/photo${query}`, { method: 'POST', body: formData });
            closeModal();
            toast('Wear logged with photo!');
            renderTodayView(document.getElementById('main-content'));
        } catch (err) {
            toast(err.message, 'error');
        }
    });
}

async function openWoreElseModal() {
    // Load ACTIVE items only
    let allItems = [];
    try {
        allItems = await api('/items?lifecycle=active');
    } catch (err) {
        toast(err.message, 'error');
        return;
    }

    const categories = state.settings?.categories || [];
    const categoryNames = categories.map(c => typeof c === 'string' ? c : c.name);
    const seasonTags = state.settings?.season_tags || [];
    const vibeTags = state.settings?.vibe_tags || [];
    const thresholds = state.settings?.dirty_thresholds || {};

    // Group items by category
    const grouped = {};
    categoryNames.forEach(c => grouped[c] = []);
    allItems.forEach(item => {
        if (grouped[item.category]) {
            grouped[item.category].push(item);
        } else {
            grouped[item.category] = [item];
        }
    });

    let itemPickerHtml = '';
    Object.entries(grouped).forEach(([cat, items]) => {
        if (items.length === 0) return;
        itemPickerHtml += `<div class="wore-else-category">${escapeHtml(cat)}</div>`;
        itemPickerHtml += items.map(item => `
            <div class="list-item selectable" data-item-id="${item.id}" data-category="${escapeHtml(item.category)}" data-wears="${item.wears_since_wash}">
                <div class="list-item-photo">${getItemThumbHtml(item)}</div>
                <div class="list-item-content">
                    <div class="list-item-title">#${item.number} ${escapeHtml(item.name)}</div>
                    <div class="list-item-subtitle">${item.status} - ${item.wears_since_wash} wears since wash</div>
                </div>
            </div>
        `).join('');
    });

    const seasonChipsHtml = seasonTags.map(t =>
        `<span class="chip" data-tag="${escapeHtml(t)}" data-type="season">${escapeHtml(t)}</span>`
    ).join('');

    const vibeChipsHtml = vibeTags.map(t =>
        `<span class="chip" data-tag="${escapeHtml(t)}" data-type="vibe">${escapeHtml(t)}</span>`
    ).join('');

    openModal(`
        <div class="modal-header">
            <span class="modal-title">Log Ad-hoc Wear</span>
            <button class="modal-close" onclick="closeModal()">&times;</button>
        </div>
        <div class="modal-body">
            <div class="form-group">
                <label class="form-label">Selected Items</label>
                <div class="chip-row" id="wore-else-selected"></div>
            </div>
            <div class="form-group">
                <label class="form-label">Pick Items</label>
                <div class="search-bar">
                    <input type="text" placeholder="Search items..." id="wore-else-search">
                </div>
                <div id="wore-else-picker" style="max-height: 200px; overflow-y: auto;">${itemPickerHtml}</div>
            </div>
            <div class="form-group" id="wore-else-dirty-section" style="display: none;">
                <label class="form-label">Item Status After Wearing</label>
                <div id="wore-else-dirty-toggles"></div>
            </div>
            <div class="form-group">
                <label class="toggle-group">
                    <span class="toggle-label">Save as outfit</span>
                    <div class="toggle" id="save-as-outfit-toggle"></div>
                </label>
            </div>
            <div id="save-outfit-fields" style="display: none;">
                <div class="form-group">
                    <label class="form-label">Outfit Name</label>
                    <input type="text" class="form-input" id="wore-else-outfit-name" placeholder="New outfit name...">
                </div>
                <div class="form-group">
                    <label class="form-label">Season Tags</label>
                    <div class="chip-row" id="wore-else-season-tags">${seasonChipsHtml}</div>
                </div>
                <div class="form-group">
                    <label class="form-label">Vibe Tags</label>
                    <div class="chip-row" id="wore-else-vibe-tags">${vibeChipsHtml}</div>
                </div>
            </div>
        </div>
        <div class="modal-footer">
            <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
            <button class="btn btn-primary" id="wore-else-submit-btn">Log Wear</button>
        </div>
    `, true);

    const selectedSet = new Set();
    const dirtyMap = new Map(); // item_id -> dirty boolean

    function updateSelectedDisplay() {
        const display = document.getElementById('wore-else-selected');
        const selected = allItems.filter(i => selectedSet.has(i.id));
        display.innerHTML = selected.map(i =>
            `<span class="chip small">#${i.number} ${escapeHtml(i.name)}</span>`
        ).join('') || '<span class="text-muted">None selected</span>';

        // Update dirty toggles section
        const dirtySection = document.getElementById('wore-else-dirty-section');
        const dirtyToggles = document.getElementById('wore-else-dirty-toggles');

        if (selected.length > 0) {
            dirtySection.style.display = 'block';
            dirtyToggles.innerHTML = selected.map(item => {
                const threshold = thresholds[item.category] || 0;
                const wouldBeDirty = threshold > 0 && (item.wears_since_wash + 1) >= threshold;
                // Initialize dirty state if not set
                if (!dirtyMap.has(item.id)) {
                    dirtyMap.set(item.id, wouldBeDirty);
                }
                const isDirty = dirtyMap.get(item.id);

                return `
                    <div class="wore-else-dirty-item">
                        <span>${escapeHtml(item.name)}</span>
                        <div class="toggle ${isDirty ? '' : 'active'}" data-item-id="${item.id}"></div>
                        <span class="dirty-label">${isDirty ? 'Now dirty' : 'Still clean'}</span>
                    </div>
                `;
            }).join('');

            // Attach toggle handlers
            dirtyToggles.querySelectorAll('.toggle').forEach(toggle => {
                toggle.addEventListener('click', () => {
                    const itemId = parseInt(toggle.dataset.itemId);
                    const currentDirty = dirtyMap.get(itemId);
                    dirtyMap.set(itemId, !currentDirty);
                    toggle.classList.toggle('active', currentDirty);
                    toggle.nextElementSibling.textContent = currentDirty ? 'Still clean' : 'Now dirty';
                });
            });
        } else {
            dirtySection.style.display = 'none';
        }
    }

    updateSelectedDisplay();

    // Item picker
    document.getElementById('wore-else-picker').addEventListener('click', (e) => {
        const listItem = e.target.closest('.list-item');
        if (!listItem) return;
        const itemId = parseInt(listItem.dataset.itemId);
        if (selectedSet.has(itemId)) {
            selectedSet.delete(itemId);
            dirtyMap.delete(itemId);
            listItem.classList.remove('selected');
        } else {
            selectedSet.add(itemId);
            listItem.classList.add('selected');
        }
        updateSelectedDisplay();
    });

    // Search
    document.getElementById('wore-else-search').addEventListener('input', (e) => {
        const q = e.target.value.toLowerCase();
        document.querySelectorAll('#wore-else-picker .list-item').forEach(el => {
            const text = el.textContent.toLowerCase();
            el.style.display = text.includes(q) ? '' : 'none';
        });
        // Also hide category headers if all items under them are hidden
        document.querySelectorAll('#wore-else-picker .wore-else-category').forEach(cat => {
            let nextEl = cat.nextElementSibling;
            let hasVisible = false;
            while (nextEl && !nextEl.classList.contains('wore-else-category')) {
                if (nextEl.style.display !== 'none') hasVisible = true;
                nextEl = nextEl.nextElementSibling;
            }
            cat.style.display = hasVisible ? '' : 'none';
        });
    });

    // Save as outfit toggle
    document.getElementById('save-as-outfit-toggle').addEventListener('click', function() {
        this.classList.toggle('active');
        document.getElementById('save-outfit-fields').style.display = this.classList.contains('active') ? 'block' : 'none';
    });

    // Tag pickers
    ['wore-else-season-tags', 'wore-else-vibe-tags'].forEach(id => {
        document.getElementById(id)?.addEventListener('click', (e) => {
            const chip = e.target.closest('.chip');
            if (chip) chip.classList.toggle('active');
        });
    });

    // Submit
    document.getElementById('wore-else-submit-btn').addEventListener('click', async () => {
        if (selectedSet.size === 0) {
            toast('Select at least one item', 'error');
            return;
        }

        const items = Array.from(selectedSet).map(id => ({
            item_id: id,
            dirty: dirtyMap.get(id) ?? true
        }));

        const saveAsOutfitToggle = document.getElementById('save-as-outfit-toggle');
        const wantsSaveOutfit = saveAsOutfitToggle.classList.contains('active');
        const outfitName = document.getElementById('wore-else-outfit-name').value.trim();

        // Validate: if checkbox is on, name must be provided
        if (wantsSaveOutfit && !outfitName) {
            toast('Please enter an outfit name', 'error');
            return;
        }

        const body = { items, date: localToday() };

        if (wantsSaveOutfit && outfitName) {
            const seasonTagEls = document.querySelectorAll('#wore-else-season-tags .chip.active');
            const vibeTagEls = document.querySelectorAll('#wore-else-vibe-tags .chip.active');
            body.save_as_outfit = {
                name: outfitName,
                season_tags: Array.from(seasonTagEls).map(el => el.dataset.tag),
                vibe_tags: Array.from(vibeTagEls).map(el => el.dataset.tag)
            };
        }

        try {
            const result = await api('/wear', { method: 'POST', body });
            // Show photo upload follow-up prompt
            showWearPhotoPrompt(result.event_id, result.created_outfit || null);
        } catch (err) {
            toast(err.message, 'error');
        }
    });
}

// ========================================
// CLOSET VIEW
// ========================================

async function renderClosetView(container) {
    container.innerHTML = '<div class="flex-center"><div class="spinner"></div></div>';

    try {
        // Pass lifecycle param unless 'all'
        const lifecycleParam = state.closetFilters.lifecycle === 'all' ? '' : state.closetFilters.lifecycle;
        const url = lifecycleParam ? `/items?lifecycle=${lifecycleParam}` : '/items';
        [, , state.items] = await Promise.all([
            loadSettings(),
            loadActiveTrip(),
            api(url)
        ]);
        // Load wishlist if needed
        if (state.closetSubview === 'wishlist') {
            state.wishlist = await api('/wishlist');
        }
        if (state.closetSubview === 'scents') {
            state.scents = await api(`/scents?sort=${encodeURIComponent(state.scentFilters.sort)}`);
        }
    } catch (err) {
        container.innerHTML = `<div class="empty-state"><div class="empty-state-text">Error: ${escapeHtml(err.message)}</div></div>`;
        return;
    }

    // Segmented control for Closet/Wishlist/Scents
    const segmentedHtml = `
        <div class="segmented-control" id="closet-segment">
            <button class="segment-btn ${state.closetSubview === 'closet' ? 'active' : ''}" data-subview="closet">Closet</button>
            <button class="segment-btn ${state.closetSubview === 'wishlist' ? 'active' : ''}" data-subview="wishlist">Wishlist</button>
            <button class="segment-btn ${state.closetSubview === 'scents' ? 'active' : ''}" data-subview="scents">Scents</button>
        </div>
    `;

    if (state.closetSubview === 'wishlist') {
        renderWishlistView(container, segmentedHtml);
        return;
    }

    if (state.closetSubview === 'scents') {
        renderScentsView(container, segmentedHtml);
        return;
    }

    const categories = state.settings?.categories || [];
    const categoryNames = ['', ...categories.map(c => typeof c === 'string' ? c : c.name)];

    let filtered = state.items;

    // Vacation mode filtering (unless "Show all" toggled)
    if (state.activeTrip && !state.closetShowAll) {
        const tripItemIds = new Set(state.activeTrip.item_ids || []);
        filtered = filtered.filter(i => tripItemIds.has(i.id));
    }

    if (state.closetFilters.category) {
        filtered = filtered.filter(i => i.category === state.closetFilters.category);
    }
    if (state.closetFilters.status) {
        filtered = filtered.filter(i => i.status === state.closetFilters.status);
    }
    if (state.closetFilters.search) {
        const q = state.closetFilters.search.toLowerCase();
        filtered = filtered.filter(i =>
            i.name.toLowerCase().includes(q) ||
            String(i.number).includes(q) ||
            (i.brand && i.brand.toLowerCase().includes(q))
        );
    }

    const categoryChipsHtml = categoryNames.map(c =>
        `<span class="chip ${state.closetFilters.category === c ? 'active' : ''}" data-category="${escapeHtml(c)}">${c || 'All'}</span>`
    ).join('');

    // Lifecycle filter chips
    const lifecycles = [
        { value: 'active', label: 'Active' },
        { value: 'stored', label: 'Stored' },
        { value: 'retired', label: 'Retired' },
        { value: 'all', label: 'All' }
    ];
    const lifecycleChipsHtml = lifecycles.map(l =>
        `<span class="chip ${state.closetFilters.lifecycle === l.value ? 'active' : ''}" data-lifecycle="${l.value}">${l.label}</span>`
    ).join('');

    const itemsHtml = filtered.length === 0
        ? '<div class="empty-state"><div class="empty-state-text">No items found</div></div>'
        : `<div class="item-grid">${filtered.map(item => renderItemCard(item, state.closetFilters.lifecycle)).join('')}</div>`;

    let vacationNoteHtml = '';
    if (state.activeTrip && !state.closetShowAll) {
        vacationNoteHtml = `<div class="inline-note">Showing packed items only · <span class="link-text" id="closet-show-all">Show all</span></div>`;
    } else if (state.activeTrip && state.closetShowAll) {
        vacationNoteHtml = `<div class="inline-note">Showing all items · <span class="link-text" id="closet-show-all">Hide unpacked</span></div>`;
    }

    container.innerHTML = `
        ${renderVacationBanner()}
        ${segmentedHtml}
        <div class="search-bar">
            <input type="text" placeholder="Search items..." id="closet-search" value="${escapeHtml(state.closetFilters.search)}">
        </div>
        ${vacationNoteHtml}
        <div class="chip-row scrollable" id="lifecycle-filter">${lifecycleChipsHtml}</div>
        <div class="chip-row scrollable" id="category-filter">${categoryChipsHtml}</div>
        <div class="chip-row">
            <span class="chip ${state.closetFilters.status === '' ? 'active' : ''}" data-status="">All</span>
            <span class="chip ${state.closetFilters.status === 'clean' ? 'active' : ''}" data-status="clean">Clean</span>
            <span class="chip ${state.closetFilters.status === 'dirty' ? 'active' : ''}" data-status="dirty">Dirty</span>
        </div>
        ${itemsHtml}
        <button class="fab" id="add-item-btn">+</button>
    `;

    setupVacationBanner(container);

    // Vacation "Show all" toggle
    const showAllBtn = container.querySelector('#closet-show-all');
    if (showAllBtn) {
        showAllBtn.addEventListener('click', () => {
            state.closetShowAll = !state.closetShowAll;
            renderClosetView(container);
        });
    }

    // Segment control
    document.getElementById('closet-segment').addEventListener('click', (e) => {
        const btn = e.target.closest('.segment-btn');
        if (!btn) return;
        state.closetSubview = btn.dataset.subview;
        renderClosetView(container);
    });

    // Search
    document.getElementById('closet-search').addEventListener('input', (e) => {
        state.closetFilters.search = e.target.value;
        renderClosetView(container);
    });

    // Lifecycle filter
    document.getElementById('lifecycle-filter').addEventListener('click', (e) => {
        const chip = e.target.closest('.chip');
        if (!chip) return;
        state.closetFilters.lifecycle = chip.dataset.lifecycle;
        renderClosetView(container);
    });

    // Category filter
    document.getElementById('category-filter').addEventListener('click', (e) => {
        const chip = e.target.closest('.chip');
        if (!chip) return;
        state.closetFilters.category = chip.dataset.category;
        renderClosetView(container);
    });

    // Status filter
    container.querySelectorAll('[data-status]').forEach(chip => {
        chip.addEventListener('click', () => {
            state.closetFilters.status = chip.dataset.status;
            renderClosetView(container);
        });
    });

    // Item cards
    container.querySelectorAll('.item-card').forEach(card => {
        card.addEventListener('click', () => {
            const itemId = parseInt(card.dataset.itemId);
            const item = state.items.find(i => i.id === itemId);
            if (item) openItemModal(item);
        });
    });

    // Add button
    document.getElementById('add-item-btn').addEventListener('click', () => {
        openItemModal(null);
    });
}

function renderWishlistView(container, segmentedHtml) {
    const wishlist = state.wishlist || [];

    const cardsHtml = wishlist.length === 0
        ? '<div class="empty-state"><div class="empty-state-text">No wishlist items yet</div></div>'
        : wishlist.map(item => `
            <div class="wishlist-card" data-wishlist-id="${item.id}">
                <div class="wishlist-photo">
                    ${item.image ? `<img src="${escapeHtml(item.image)}" alt="${escapeHtml(item.name)}" loading="lazy">` : `<span class="placeholder">?</span>`}
                </div>
                <div class="wishlist-info">
                    <div class="wishlist-name">${escapeHtml(item.name || 'Untitled')}</div>
                    ${item.brand ? `<div class="wishlist-brand">${escapeHtml(item.brand)}</div>` : ''}
                    ${item.price ? `<div class="wishlist-price">${formatCurrency(item.price)}</div>` : ''}
                    ${item.fills_gap ? `<div class="wishlist-badge fills-gap">${escapeHtml(item.fills_gap)}</div>` : ''}
                </div>
                <div class="wishlist-actions">
                    ${item.url ? `<a href="${escapeHtml(item.url)}" target="_blank" class="btn btn-sm btn-outline wishlist-link-btn" onclick="event.stopPropagation()">View</a>` : ''}
                    <button class="btn btn-sm btn-primary wishlist-buy-btn" data-id="${item.id}">Bought</button>
                </div>
            </div>
        `).join('');

    container.innerHTML = `
        ${segmentedHtml}
        <button class="btn btn-primary btn-block mb-md" id="add-wishlist-btn">+ Add from link</button>
        ${cardsHtml}
    `;

    // Segment control
    document.getElementById('closet-segment').addEventListener('click', (e) => {
        const btn = e.target.closest('.segment-btn');
        if (!btn) return;
        state.closetSubview = btn.dataset.subview;
        renderClosetView(container);
    });

    // Add wishlist item
    document.getElementById('add-wishlist-btn').addEventListener('click', () => {
        openAddWishlistModal();
    });

    // Card click for edit
    container.querySelectorAll('.wishlist-card').forEach(card => {
        card.addEventListener('click', () => {
            const id = parseInt(card.dataset.wishlistId);
            const item = wishlist.find(w => w.id === id);
            if (item) openEditWishlistModal(item);
        });
    });

    // Buy buttons
    container.querySelectorAll('.wishlist-buy-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const id = parseInt(btn.dataset.id);
            const item = wishlist.find(w => w.id === id);
            if (item) openPurchaseWishlistModal(item);
        });
    });
}

function openAddWishlistModal() {
    const categories = state.settings?.categories || [];
    const categoryNames = categories.map(c => typeof c === 'string' ? c : c.name);
    const categoryOptions = categoryNames.map(c =>
        `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`
    ).join('');

    openModal(`
        <div class="modal-header">
            <span class="modal-title">Add to Wishlist</span>
            <button class="modal-close" onclick="closeModal()">&times;</button>
        </div>
        <div class="modal-body">
            <div class="form-group">
                <label class="form-label">Product URL</label>
                <input type="url" class="form-input" id="wishlist-url" placeholder="https://...">
            </div>
            <div class="form-group">
                <label class="form-label">Category (optional)</label>
                <select class="form-select" id="wishlist-category">
                    <option value="">Select...</option>
                    ${categoryOptions}
                </select>
            </div>
        </div>
        <div class="modal-footer">
            <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
            <button class="btn btn-primary" id="add-wishlist-submit">Add</button>
        </div>
    `);

    document.getElementById('add-wishlist-submit').addEventListener('click', async () => {
        const url = document.getElementById('wishlist-url').value.trim();
        const category = document.getElementById('wishlist-category').value;

        if (!url) {
            toast('Please enter a URL', 'error');
            return;
        }

        try {
            const body = { url };
            if (category) body.category = category;
            await api('/wishlist', { method: 'POST', body });
            closeModal();
            toast('Added to wishlist!');
            state.wishlist = await api('/wishlist');
            renderClosetView(document.getElementById('main-content'));
        } catch (err) {
            toast(err.message, 'error');
        }
    });
}

function openEditWishlistModal(item) {
    const categories = state.settings?.categories || [];
    const categoryNames = categories.map(c => typeof c === 'string' ? c : c.name);
    const categoryOptions = categoryNames.map(c =>
        `<option value="${escapeHtml(c)}" ${item.category === c ? 'selected' : ''}>${escapeHtml(c)}</option>`
    ).join('');

    openModal(`
        <div class="modal-header">
            <span class="modal-title">Edit Wishlist Item</span>
            <button class="modal-close" onclick="closeModal()">&times;</button>
        </div>
        <div class="modal-body">
            <div class="form-group">
                <label class="form-label">Name</label>
                <input type="text" class="form-input" id="edit-wishlist-name" value="${escapeHtml(item.name || '')}">
            </div>
            <div class="form-group">
                <label class="form-label">Brand</label>
                <input type="text" class="form-input" id="edit-wishlist-brand" value="${escapeHtml(item.brand || '')}">
            </div>
            <div class="form-group">
                <label class="form-label">Price</label>
                <input type="number" step="0.01" class="form-input" id="edit-wishlist-price" value="${item.price || ''}">
            </div>
            <div class="form-group">
                <label class="form-label">Category</label>
                <select class="form-select" id="edit-wishlist-category">
                    <option value="">Select...</option>
                    ${categoryOptions}
                </select>
            </div>
            <div class="form-group">
                <label class="form-label">Notes</label>
                <textarea class="form-textarea" id="edit-wishlist-notes">${escapeHtml(item.notes || '')}</textarea>
            </div>
        </div>
        <div class="modal-footer">
            <button class="btn btn-danger" id="delete-wishlist-btn">Delete</button>
            <button class="btn btn-primary" id="save-wishlist-btn">Save</button>
        </div>
    `);

    document.getElementById('save-wishlist-btn').addEventListener('click', async () => {
        const body = {
            name: document.getElementById('edit-wishlist-name').value.trim(),
            brand: document.getElementById('edit-wishlist-brand').value.trim(),
            price: parseFloat(document.getElementById('edit-wishlist-price').value) || null,
            category: document.getElementById('edit-wishlist-category').value || null,
            notes: document.getElementById('edit-wishlist-notes').value.trim()
        };

        try {
            await api(`/wishlist/${item.id}`, { method: 'PATCH', body });
            closeModal();
            toast('Wishlist item updated!');
            state.wishlist = await api('/wishlist');
            renderClosetView(document.getElementById('main-content'));
        } catch (err) {
            toast(err.message, 'error');
        }
    });

    document.getElementById('delete-wishlist-btn').addEventListener('click', async () => {
        if (!confirm('Delete this wishlist item?')) return;
        try {
            await api(`/wishlist/${item.id}`, { method: 'DELETE' });
            closeModal();
            toast('Wishlist item deleted');
            state.wishlist = await api('/wishlist');
            renderClosetView(document.getElementById('main-content'));
        } catch (err) {
            toast(err.message, 'error');
        }
    });
}

function openPurchaseWishlistModal(item) {
    openModal(`
        <div class="modal-header">
            <span class="modal-title">Mark as Purchased</span>
            <button class="modal-close" onclick="closeModal()">&times;</button>
        </div>
        <div class="modal-body">
            <div class="form-group">
                <label class="form-label">Item Number (optional)</label>
                <input type="number" class="form-input" id="purchase-item-number" placeholder="e.g. 42">
                <div class="form-hint">Leave blank to assign the next number automatically.</div>
            </div>
            ${!item.category ? '<p class="text-muted" style="font-size: 13px;">Note: This item needs a category set before purchase.</p>' : ''}
        </div>
        <div class="modal-footer">
            <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
            <button class="btn btn-primary" id="confirm-purchase-btn">Add to Closet</button>
        </div>
    `);

    document.getElementById('confirm-purchase-btn').addEventListener('click', async () => {
        const number = parseInt(document.getElementById('purchase-item-number').value);
        // Blank is fine — the server assigns max + 1.
        const body = isNaN(number) ? {} : { number };

        try {
            const result = await api(`/wishlist/${item.id}/purchase`, {
                method: 'POST',
                body
            });
            closeModal();
            toast(`Added to closet as #${result.number}!`);
            state.wishlist = await api('/wishlist');
            state.items = await api('/items');
            renderClosetView(document.getElementById('main-content'));
        } catch (err) {
            toast(err.message, 'error');
        }
    });
}

function renderItemCard(item, currentLifecycleFilter) {
    const lifecycle = item.lifecycle || 'active';
    const showLifecycleLabel = lifecycle !== 'active';
    // Only show status dot for active items
    const statusDotHtml = lifecycle === 'active'
        ? `<div class="item-status-dot ${item.status}"></div>`
        : '';

    return `
        <div class="item-card ${showLifecycleLabel ? 'lifecycle-muted' : ''}" data-item-id="${item.id}">
            <div class="item-photo">
                ${getItemThumbHtml(item)}
                ${statusDotHtml}
                ${showLifecycleLabel ? `<div class="item-lifecycle-label">${escapeHtml(lifecycle)}</div>` : ''}
            </div>
            <div class="item-info">
                <div class="item-number">#${escapeHtml(item.number)}</div>
                <div class="item-name">${escapeHtml(item.name)}</div>
                <div class="item-meta">
                    <span>${escapeHtml(item.category)}</span>
                    <span>${item.lifetime_wears} wears</span>
                </div>
            </div>
        </div>
    `;
}

function compositionRowHtml(pct, fiber) {
    const pctVal = (pct === 0 || pct) ? escapeHtml(pct) : '';
    return `
        <div class="comp-row">
            <input type="number" class="form-input comp-pct" min="1" max="100" step="1"
                   inputmode="numeric" placeholder="%" value="${pctVal}">
            <input type="text" class="form-input comp-fiber" list="fiber-options"
                   placeholder="fiber" value="${escapeHtml(fiber || '')}">
            <button type="button" class="comp-remove" aria-label="Remove fiber">&times;</button>
        </div>
    `;
}

function openItemModal(item) {
    const isNew = !item;
    const title = isNew ? 'Add Item' : 'Edit Item';

    const categories = state.settings?.categories || [];
    const categoryNames = categories.map(c => typeof c === 'string' ? c : c.name);
    const seasonTags = state.settings?.season_tags || [];
    const vibeTags = state.settings?.vibe_tags || [];
    const materials = state.settings?.materials || [];

    const categoryOptions = categoryNames.map(c =>
        `<option value="${escapeHtml(c)}" ${item?.category === c ? 'selected' : ''}>${escapeHtml(c)}</option>`
    ).join('');

    // Lifecycle options
    const lifecycleOptions = ['active', 'stored', 'retired'].map(l => {
        const currentLifecycle = item?.lifecycle || 'active';
        return `<option value="${l}" ${currentLifecycle === l ? 'selected' : ''}>${l.charAt(0).toUpperCase() + l.slice(1)}</option>`;
    }).join('');

    const seasonChipsHtml = seasonTags.map(t => {
        const selected = item?.season_tags?.includes(t);
        return `<span class="chip ${selected ? 'active' : ''}" data-tag="${escapeHtml(t)}" data-type="season">${escapeHtml(t)}</span>`;
    }).join('');

    const vibeChipsHtml = vibeTags.map(t => {
        const selected = item?.vibe_tags?.includes(t);
        return `<span class="chip ${selected ? 'active' : ''}" data-tag="${escapeHtml(t)}" data-type="vibe">${escapeHtml(t)}</span>`;
    }).join('');

    const materialChipsHtml = materials.map(m => {
        const selected = item?.materials?.includes(m);
        return `<span class="chip ${selected ? 'active' : ''}" data-tag="${escapeHtml(m)}" data-type="material">${escapeHtml(m)}</span>`;
    }).join('');

    let extraInfo = '';
    if (item) {
        const cpw = item.price > 0 && item.lifetime_wears > 0
            ? formatCurrency(item.price / item.lifetime_wears)
            : '-';
        extraInfo = `
            <div class="form-group">
                <label class="form-label">Stats</label>
                <div style="color: var(--text-secondary); font-size: 14px;">
                    Lifecycle: ${escapeHtml(item.lifecycle || 'active')}<br>
                    Lifetime wears: ${item.lifetime_wears}<br>
                    Wears since wash: ${item.wears_since_wash}<br>
                    Last worn: ${formatDate(item.last_worn)}<br>
                    Cost per wear: ${cpw}
                </div>
            </div>
        `;
    }

    // Photo gallery HTML for existing items
    const photos = item?.photos || [];
    const coverUrl = item?.photo || '';
    let photoGalleryHtml = '';
    if (item && photos.length > 0) {
        photoGalleryHtml = `
            <div class="form-group">
                <label class="form-label">Photos</label>
                <div class="photo-strip" id="item-photo-strip">
                    ${photos.map(p => `
                        <div class="photo-strip-item ${p.url === coverUrl ? 'is-cover' : ''}" data-photo-id="${p.id}" data-photo-url="${escapeHtml(p.url)}">
                            <img src="${escapeHtml(bustedPhotoUrl(p.url, item.id))}" alt="Item photo">
                            ${p.url === coverUrl ? '<div class="cover-badge">Cover</div>' : ''}
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }

    // Number: new items get their number assigned by the server (max + 1).
    // Show what it will most likely be, but never send it.
    let nextNumberLabel = 'auto';
    if (isNew) {
        const nums = (state.items || [])
            .map(i => parseInt(i.number))
            .filter(n => !isNaN(n));
        if (nums.length) nextNumberLabel = `#${Math.max(...nums) + 1} (auto)`;
    }

    const numberFieldHtml = isNew
        ? `
            <div class="form-group form-group-auto">
                <label class="form-label">Number</label>
                <div class="form-static-note">${escapeHtml(nextNumberLabel)}</div>
            </div>
        `
        : `
            <div class="form-group">
                <label class="form-label">Number</label>
                <input type="number" class="form-input" name="number" value="${item?.number || ''}" required>
            </div>
        `;

    const brandOptions = datalistOptionsHtml(existingItemValues('brand'));
    const colorOptions = datalistOptionsHtml(existingItemValues('color'));
    const fiberOptions = datalistOptionsHtml(FIBER_OPTIONS);

    // Fabric composition rows (prefilled when editing)
    const existingComposition = Array.isArray(item?.composition) ? item.composition : [];
    const compositionRowsHtml = (existingComposition.length ? existingComposition : [{ pct: '', fiber: '' }])
        .map(c => compositionRowHtml(c.pct, c.fiber))
        .join('');

    // Care method only matters on create — the server never regenerates
    // care_notes on PATCH, so showing the select on edit would just mislead.
    const careMethodHtml = isNew ? `
        <div class="form-group">
            <label class="form-label">Care</label>
            <select class="form-select" name="care_method">
                <option value="">Select...</option>
                ${CARE_METHOD_OPTIONS.map(o => `<option value="${escapeHtml(o)}">${escapeHtml(o)}</option>`).join('')}
            </select>
        </div>
    ` : '';

    // Link import section for new items
    const linkImportHtml = isNew ? `
        <div class="form-group link-import-section">
            <label class="form-label">Paste product link</label>
            <div class="form-row">
                <input type="url" class="form-input" id="import-link-url" placeholder="https://...">
                <button type="button" class="btn btn-secondary" id="fetch-link-btn">Fetch</button>
            </div>
            <div id="link-import-status" class="hidden"></div>
            <div id="link-import-preview" class="hidden">
                <img id="link-import-image" class="file-preview">
            </div>
        </div>
    ` : '';

    openModal(`
        <div class="modal-header">
            <span class="modal-title">${title}</span>
            <button class="modal-close" onclick="closeModal()">&times;</button>
        </div>
        <div class="modal-body">
            <form id="item-form">
                ${linkImportHtml}
                <div class="form-row">
                    ${numberFieldHtml}
                    <div class="form-group">
                        <label class="form-label">Name</label>
                        <input type="text" class="form-input" name="name" value="${escapeHtml(item?.name || '')}"
                               placeholder="e.g. AG Everett Sateen Slim Straight Pants" required>
                        <div class="form-hint">Convention: Brand + product name</div>
                    </div>
                </div>
                <div class="form-group">
                    <label class="form-label">Category</label>
                    <select class="form-select" name="category" required>
                        <option value="">Select...</option>
                        ${categoryOptions}
                    </select>
                </div>
                <div class="form-group">
                    <label class="form-label">Lifecycle</label>
                    <select class="form-select" name="lifecycle">
                        ${lifecycleOptions}
                    </select>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label">Brand</label>
                        <input type="text" class="form-input" name="brand" list="brand-options"
                               value="${escapeHtml(item?.brand || '')}">
                        <datalist id="brand-options">${brandOptions}</datalist>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Color</label>
                        <input type="text" class="form-input" name="color" list="color-options"
                               value="${escapeHtml(item?.color || '')}">
                        <datalist id="color-options">${colorOptions}</datalist>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label">Size</label>
                        <input type="text" class="form-input" name="size" value="${escapeHtml(item?.size || '')}">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Price</label>
                        <input type="number" step="0.01" class="form-input" name="price" value="${item?.price || ''}">
                    </div>
                </div>
                <div class="form-group">
                    <label class="form-label">Fabric</label>
                    <div id="composition-rows">${compositionRowsHtml}</div>
                    <div class="comp-footer">
                        <button type="button" class="btn btn-outline btn-sm" id="add-fiber-btn">+ Add fiber</button>
                        <span class="comp-total" id="comp-total">0%</span>
                    </div>
                    <datalist id="fiber-options">${fiberOptions}</datalist>
                </div>
                ${careMethodHtml}
                <div class="form-group">
                    <label class="form-label">Care notes (optional — auto-filled from fabric + care if left blank)</label>
                    <textarea class="form-textarea" name="care_notes">${escapeHtml(item?.care_notes || '')}</textarea>
                </div>
                <div class="form-group">
                    <label class="form-label">Season Tags</label>
                    <div class="chip-row" id="season-tag-picker">${seasonChipsHtml}</div>
                </div>
                <div class="form-group">
                    <label class="form-label">Vibe Tags</label>
                    <div class="chip-row" id="vibe-tag-picker">${vibeChipsHtml}</div>
                </div>
                <div class="form-group">
                    <label class="form-label">Materials</label>
                    <div class="chip-row" id="material-picker">${materialChipsHtml}</div>
                    <div class="form-hint">Auto-selected from fabric when left untouched (new items)</div>
                </div>
                ${photoGalleryHtml}
                <div class="form-group">
                    <label class="form-label">${item ? 'Add Photo' : 'Photo'}</label>
                    <div class="file-input-wrapper">
                        <input type="file" class="file-input" accept="image/*" id="photo-input">
                        <div class="file-input-btn">
                            <span>Tap to take or choose photo</span>
                        </div>
                    </div>
                    <img class="file-preview hidden" id="photo-preview">
                </div>
                ${extraInfo}
            </form>
        </div>
        <div class="modal-footer">
            ${item ? `
                <button class="btn btn-outline" id="item-care-btn">Care</button>
                <button class="btn btn-outline" id="toggle-status-btn">${item.status === 'clean' ? 'Mark Dirty' : 'Mark Clean'}</button>
                <button class="btn btn-danger" id="delete-item-btn">Delete</button>
            ` : ''}
            <button class="btn btn-primary" id="save-item-btn">Save</button>
        </div>
    `, true);

    // Store fetched image_url for new item creation
    let fetchedImageUrl = null;

    // Link import functionality
    document.getElementById('fetch-link-btn')?.addEventListener('click', async () => {
        const urlInput = document.getElementById('import-link-url');
        const url = urlInput.value.trim();
        if (!url) {
            toast('Please enter a URL', 'error');
            return;
        }

        const statusEl = document.getElementById('link-import-status');
        const previewEl = document.getElementById('link-import-preview');
        const imageEl = document.getElementById('link-import-image');

        statusEl.classList.remove('hidden');
        statusEl.innerHTML = '<div class="spinner" style="margin: 8px auto;"></div>';
        previewEl.classList.add('hidden');

        try {
            const result = await api('/import/link', { method: 'POST', body: { url } });
            if (result.found) {
                // Prefill form fields
                if (result.name) document.querySelector('[name="name"]').value = result.name;
                if (result.brand) document.querySelector('[name="brand"]').value = result.brand;
                if (result.price) document.querySelector('[name="price"]').value = result.price;

                // Show source badge
                statusEl.innerHTML = `<span class="chip small" style="background: var(--success); color: var(--bg-primary);">${escapeHtml(result.source || 'from page data')}</span>`;

                // Show image preview if available
                if (result.image_url) {
                    fetchedImageUrl = result.image_url;
                    imageEl.src = result.image_url;
                    previewEl.classList.remove('hidden');
                }
            } else {
                statusEl.innerHTML = `<span class="text-muted">${escapeHtml(result.error || 'Could not extract product info')}</span>`;
            }
        } catch (err) {
            statusEl.innerHTML = `<span style="color: var(--danger);">${escapeHtml(err.message)}</span>`;
        }
    });

    // Photo strip interactions (tap to view, long actions)
    document.getElementById('item-photo-strip')?.addEventListener('click', (e) => {
        const photoItem = e.target.closest('.photo-strip-item');
        if (!photoItem) return;
        const photoUrl = photoItem.dataset.photoUrl;
        const photoId = photoItem.dataset.photoId;
        openPhotoActionsModal(item, photoId, photoUrl);
    });

    // Photo preview
    document.getElementById('photo-input').addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (file) {
            const preview = document.getElementById('photo-preview');
            preview.src = URL.createObjectURL(file);
            preview.classList.remove('hidden');
        }
    });

    // Tag pickers
    ['season-tag-picker', 'vibe-tag-picker'].forEach(id => {
        document.getElementById(id)?.addEventListener('click', (e) => {
            const chip = e.target.closest('.chip');
            if (chip) chip.classList.toggle('active');
        });
    });

    // Materials: remember whether the user actually touched the chips. If they
    // didn't and a composition was entered, the server derives materials.
    let materialsTouched = false;
    document.getElementById('material-picker')?.addEventListener('click', (e) => {
        const chip = e.target.closest('.chip');
        if (!chip) return;
        chip.classList.toggle('active');
        materialsTouched = true;
    });

    // Composition editor
    const compRowsEl = document.getElementById('composition-rows');

    function readComposition() {
        return Array.from(compRowsEl.querySelectorAll('.comp-row')).map(row => {
            const pct = parseFloat(row.querySelector('.comp-pct').value);
            const fiber = row.querySelector('.comp-fiber').value.trim();
            return { pct, fiber };
        }).filter(c => c.fiber && !isNaN(c.pct) && c.pct > 0);
    }

    function updateCompTotal() {
        const total = Array.from(compRowsEl.querySelectorAll('.comp-pct'))
            .reduce((sum, el) => sum + (parseFloat(el.value) || 0), 0);
        const badge = document.getElementById('comp-total');
        if (!badge) return;
        badge.textContent = `${Math.round(total * 10) / 10}%`;
        badge.classList.toggle('is-complete', Math.round(total * 10) / 10 === 100);
    }

    compRowsEl.addEventListener('input', updateCompTotal);
    compRowsEl.addEventListener('click', (e) => {
        const btn = e.target.closest('.comp-remove');
        if (!btn) return;
        const rows = compRowsEl.querySelectorAll('.comp-row');
        if (rows.length <= 1) {
            // Keep one empty row around rather than leaving a bare label
            btn.closest('.comp-row').querySelectorAll('input').forEach(i => { i.value = ''; });
        } else {
            btn.closest('.comp-row').remove();
        }
        updateCompTotal();
    });

    document.getElementById('add-fiber-btn')?.addEventListener('click', () => {
        compRowsEl.insertAdjacentHTML('beforeend', compositionRowHtml('', ''));
        const rows = compRowsEl.querySelectorAll('.comp-row');
        rows[rows.length - 1].querySelector('.comp-pct').focus();
        updateCompTotal();
    });

    updateCompTotal();

    // Save
    document.getElementById('save-item-btn').addEventListener('click', async () => {
        const form = document.getElementById('item-form');
        const formData = new FormData(form);

        const seasonTagEls = document.querySelectorAll('#season-tag-picker .chip.active');
        const vibeTagEls = document.querySelectorAll('#vibe-tag-picker .chip.active');
        const materialEls = document.querySelectorAll('#material-picker .chip.active');

        const composition = readComposition();

        const data = {
            name: formData.get('name'),
            category: formData.get('category'),
            lifecycle: formData.get('lifecycle') || 'active',
            brand: formData.get('brand') || '',
            color: formData.get('color') || '',
            size: formData.get('size') || '',
            price: parseFloat(formData.get('price')) || 0,
            care_notes: formData.get('care_notes') || '',
            composition,
            season_tags: Array.from(seasonTagEls).map(el => el.dataset.tag),
            vibe_tags: Array.from(vibeTagEls).map(el => el.dataset.tag)
        };

        // New items: the server assigns the next number, so don't send one.
        if (!isNew) {
            data.number = parseInt(formData.get('number'));
        }

        // care_method only feeds care_notes composition on create; PATCH ignores it.
        if (isNew) {
            const careMethod = formData.get('care_method') || '';
            if (careMethod) data.care_method = careMethod;
        }

        // Omitting `materials` on create lets the server derive them from the
        // fibers. On edit it derives nothing, so always send the chips.
        const chosenMaterials = Array.from(materialEls).map(el => el.dataset.tag);
        if (!(isNew && !materialsTouched && composition.length > 0)) {
            data.materials = chosenMaterials;
        }

        // Include fetched image_url for new items
        if (isNew && fetchedImageUrl) {
            data.image_url = fetchedImageUrl;
        }

        try {
            let savedItem;
            if (isNew) {
                savedItem = await api('/items', { method: 'POST', body: data });
                // Check for image_error in response
                if (savedItem.image_error) {
                    toast('Item created, but image download failed', 'error');
                }
            } else {
                savedItem = await api(`/items/${item.id}`, { method: 'PATCH', body: data });
            }

            // Upload photo if selected
            const photoInput = document.getElementById('photo-input');
            if (photoInput.files[0]) {
                const photoForm = new FormData();
                photoForm.append('file', photoInput.files[0]);
                await api(`/items/${savedItem.id}/photo`, { method: 'POST', body: photoForm });
            }

            closeModal();
            toast(isNew ? 'Item created!' : 'Item updated!');
            renderClosetView(document.getElementById('main-content'));
        } catch (err) {
            toast(err.message, 'error');
        }
    });

    // Care button
    document.getElementById('item-care-btn')?.addEventListener('click', () => {
        closeModal();
        openItemCareModal(item.id);
    });

    // Toggle status
    document.getElementById('toggle-status-btn')?.addEventListener('click', async () => {
        try {
            const newStatus = item.status === 'clean' ? 'dirty' : 'clean';
            await api(`/items/${item.id}`, { method: 'PATCH', body: { status: newStatus } });
            closeModal();
            toast(`Item marked ${newStatus}`);
            renderClosetView(document.getElementById('main-content'));
        } catch (err) {
            toast(err.message, 'error');
        }
    });

    // Delete
    document.getElementById('delete-item-btn')?.addEventListener('click', async () => {
        if (!confirm('Delete this item? This cannot be undone.')) return;
        try {
            await api(`/items/${item.id}`, { method: 'DELETE' });
            closeModal();
            toast('Item deleted');
            renderClosetView(document.getElementById('main-content'));
        } catch (err) {
            toast(err.message, 'error');
        }
    });
}

function openPhotoActionsModal(item, photoId, photoUrl) {
    const previewUrl = bustedPhotoUrl(photoUrl, item.id);
    openModal(`
        <div class="modal-header">
            <span class="modal-title">Photo Options</span>
            <button class="modal-close" onclick="closeModal()">&times;</button>
        </div>
        <div class="modal-body">
            <img src="${escapeHtml(previewUrl)}" class="photo-actions-preview" onclick="openFullScreenImage('${escapeHtml(previewUrl)}')">
            <p class="text-muted text-center" style="font-size: 13px; margin-top: 8px;">Tap image to view full size</p>
        </div>
        <div class="modal-footer" style="flex-direction: column; gap: 8px;">
            <button class="btn btn-secondary btn-block" id="rotate-photo-btn">Rotate 90&deg;</button>
            <button class="btn btn-secondary btn-block" id="set-cover-btn">Set as Cover</button>
            <button class="btn btn-danger btn-block" id="delete-photo-btn">Delete Photo</button>
            <button class="btn btn-outline btn-block" onclick="closeModal()">Cancel</button>
        </div>
    `);

    document.getElementById('rotate-photo-btn').addEventListener('click', async () => {
        const btn = document.getElementById('rotate-photo-btn');
        btn.disabled = true;
        try {
            const updatedItem = await api(`/items/${item.id}/photos/${photoId}/rotate`, {
                method: 'POST',
                body: { degrees: 90 }
            });
            // Same URL, different pixels — bust every img for this item.
            state.photoBust[item.id] = Date.now();
            closeModal();
            toast('Photo rotated 90°');
            openItemModal(updatedItem);
        } catch (err) {
            btn.disabled = false;
            toast(err.message, 'error');
        }
    });

    document.getElementById('set-cover-btn').addEventListener('click', async () => {
        try {
            await api(`/items/${item.id}/photos/${photoId}/cover`, { method: 'POST' });
            closeModal();
            toast('Cover photo updated!');
            // Refresh item data and reopen modal
            const updatedItem = await api(`/items/${item.id}`);
            openItemModal(updatedItem);
        } catch (err) {
            toast(err.message, 'error');
        }
    });

    document.getElementById('delete-photo-btn').addEventListener('click', async () => {
        if (!confirm('Delete this photo?')) return;
        try {
            await api(`/items/${item.id}/photos/${photoId}`, { method: 'DELETE' });
            closeModal();
            toast('Photo deleted');
            // Refresh item data and reopen modal
            const updatedItem = await api(`/items/${item.id}`);
            openItemModal(updatedItem);
        } catch (err) {
            toast(err.message, 'error');
        }
    });
}

// ========================================
// SCENTS
// ========================================

const SCENT_STATUSES = [
    { value: 'owned', label: 'Owned' },
    { value: 'tried', label: 'Tried' },
    { value: 'wishlist', label: 'Wishlist' },
    { value: 'retired', label: 'Retired' }
];

const SCENT_CONCENTRATIONS = ['', 'cologne', 'edc', 'edt', 'edp', 'parfum', 'oil'];
const SCENT_SILLAGES = ['intimate', 'moderate', 'strong'];
const SCENT_TIMES = ['any', 'day', 'night'];

const SCENT_SORTS = [
    { value: 'rating', label: 'Top rated' },
    { value: 'recent', label: 'Recently added' },
    { value: 'name', label: 'Name' },
    { value: 'house', label: 'House' },
    { value: 'worn', label: 'Last worn' }
];

// Read-only star row. `rating` 0 means no verdict yet, which is shown as empty
// stars rather than a zero score — the two mean different things.
function starsHtml(rating, size = '') {
    const r = Math.max(0, Math.min(5, parseInt(rating) || 0));
    const stars = [1, 2, 3, 4, 5]
        .map(n => `<span class="star ${n <= r ? 'filled' : ''}">&#9733;</span>`)
        .join('');
    return `<span class="stars ${size}">${stars}</span>`;
}

// Tappable star row for forms. Reads back via readStarPicker(id).
function starPickerHtml(id, rating) {
    const r = Math.max(0, Math.min(5, parseInt(rating) || 0));
    const stars = [1, 2, 3, 4, 5]
        .map(n => `<span class="star tappable ${n <= r ? 'filled' : ''}" data-value="${n}">&#9733;</span>`)
        .join('');
    return `
        <div class="star-picker" id="${id}" data-rating="${r}">
            ${stars}
            <button type="button" class="star-clear ${r ? '' : 'hidden'}">clear</button>
        </div>
    `;
}

function setupStarPicker(id) {
    const picker = document.getElementById(id);
    if (!picker) return;
    const paint = (value) => {
        picker.dataset.rating = value;
        picker.querySelectorAll('.star').forEach(star => {
            star.classList.toggle('filled', parseInt(star.dataset.value) <= value);
        });
        picker.querySelector('.star-clear')?.classList.toggle('hidden', !value);
    };
    picker.addEventListener('click', (e) => {
        if (e.target.closest('.star-clear')) {
            paint(0);
            return;
        }
        const star = e.target.closest('.star');
        if (star) paint(parseInt(star.dataset.value));
    });
}

function readStarPicker(id) {
    return parseInt(document.getElementById(id)?.dataset.rating) || 0;
}

function scentThumbHtml(scent) {
    if (scent.photo) {
        const src = bustedPhotoUrl(scent.photo_thumb || scent.photo, `scent-${scent.id}`);
        return `<img src="${escapeHtml(src)}" alt="${escapeHtml(scent.name)}" loading="lazy">`;
    }
    // Bottle silhouette beats a broken-image box for a collection that will
    // mostly be photo-less — you journal a shop sample, you don't photograph it.
    return `
        <svg class="scent-placeholder" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M10 2h4v3h-4z"/>
            <path d="M9 5h6a3 3 0 013 3v11a3 3 0 01-3 3H9a3 3 0 01-3-3V8a3 3 0 013-3z"/>
            <path d="M6 12h12"/>
        </svg>
    `;
}

function scentSubtitle(scent) {
    // House and concentration are the identifying pair; skip the separator when
    // only one is recorded so nothing renders as a stray bullet.
    return [scent.house, (scent.concentration || '').toUpperCase()]
        .filter(Boolean).join(' · ');
}

async function renderScentsView(container, segmentedHtml) {
    const scents = state.scents || [];
    const filters = state.scentFilters;

    let filtered = scents;
    if (filters.status) {
        filtered = filtered.filter(s => (s.status || 'owned') === filters.status);
    }
    if (filters.search) {
        const q = filters.search.toLowerCase();
        filtered = filtered.filter(s =>
            (s.name || '').toLowerCase().includes(q) ||
            (s.house || '').toLowerCase().includes(q) ||
            (s.family || '').toLowerCase().includes(q) ||
            (s.impression || '').toLowerCase().includes(q) ||
            [...(s.notes_top || []), ...(s.notes_heart || []), ...(s.notes_base || [])]
                .some(n => n.includes(q))
        );
    }

    const statusChipsHtml = [{ value: '', label: 'All' }, ...SCENT_STATUSES].map(s => {
        const count = s.value
            ? scents.filter(x => (x.status || 'owned') === s.value).length
            : scents.length;
        return `<span class="chip ${filters.status === s.value ? 'active' : ''}" data-scent-status="${s.value}">${s.label}${count ? ` ${count}` : ''}</span>`;
    }).join('');

    const sortOptions = SCENT_SORTS.map(s =>
        `<option value="${s.value}" ${filters.sort === s.value ? 'selected' : ''}>${s.label}</option>`
    ).join('');

    let listHtml;
    if (scents.length === 0) {
        listHtml = `
            <div class="empty-state">
                <div class="empty-state-text">
                    No scents yet.<br>Add one you've tried and write down what you thought.
                </div>
            </div>
        `;
    } else if (filtered.length === 0) {
        listHtml = '<div class="empty-state"><div class="empty-state-text">Nothing matches those filters</div></div>';
    } else {
        listHtml = `<div class="scent-list">${filtered.map(renderScentCard).join('')}</div>`;
    }

    container.innerHTML = `
        ${segmentedHtml}
        <div class="search-bar">
            <input type="text" placeholder="Search scents, houses, notes..." id="scent-search" value="${escapeHtml(filters.search)}">
        </div>
        <div class="chip-row scrollable" id="scent-status-filter">${statusChipsHtml}</div>
        <div class="scent-toolbar">
            <select class="form-select scent-sort" id="scent-sort">${sortOptions}</select>
            <button class="btn btn-sm btn-outline" id="scent-journal-btn">Journal</button>
        </div>
        ${listHtml}
        <button class="fab" id="add-scent-btn">+</button>
    `;

    document.getElementById('closet-segment').addEventListener('click', (e) => {
        const btn = e.target.closest('.segment-btn');
        if (!btn) return;
        state.closetSubview = btn.dataset.subview;
        renderClosetView(container);
    });

    document.getElementById('scent-search').addEventListener('input', (e) => {
        state.scentFilters.search = e.target.value;
        renderScentsView(container, segmentedHtml);
    });

    document.getElementById('scent-status-filter').addEventListener('click', (e) => {
        const chip = e.target.closest('.chip');
        if (!chip) return;
        state.scentFilters.status = chip.dataset.scentStatus;
        renderScentsView(container, segmentedHtml);
    });

    // Sorting is done by the server, so this re-fetches rather than re-filters.
    document.getElementById('scent-sort').addEventListener('change', (e) => {
        state.scentFilters.sort = e.target.value;
        renderClosetView(container);
    });

    document.getElementById('scent-journal-btn').addEventListener('click', () => {
        openScentJournalModal();
    });

    container.querySelectorAll('.scent-card').forEach(card => {
        card.addEventListener('click', () => {
            openScentDetail(parseInt(card.dataset.scentId));
        });
    });

    document.getElementById('add-scent-btn').addEventListener('click', () => {
        openScentModal(null);
    });
}

function renderScentCard(scent) {
    const status = scent.status || 'owned';
    const statusLabel = SCENT_STATUSES.find(s => s.value === status)?.label || status;
    // "Owned" is the default and would be a badge on almost every card, so it
    // stays implicit; the other three are the ones worth calling out.
    const statusBadge = status === 'owned'
        ? ''
        : `<span class="scent-badge status-${status}">${escapeHtml(statusLabel)}</span>`;

    const subtitle = scentSubtitle(scent);
    const impression = (scent.impression || '').trim();
    const noteCount = scent.note_count || 0;

    const meta = [];
    if (scent.family) meta.push(escapeHtml(scent.family));
    if (noteCount) meta.push(`${noteCount} ${noteCount === 1 ? 'entry' : 'entries'}`);
    if (status === 'owned' && scent.remaining_pct !== null && scent.remaining_pct !== undefined) {
        meta.push(`${scent.remaining_pct}% left`);
    }

    return `
        <div class="scent-card" data-scent-id="${scent.id}">
            <div class="scent-thumb">${scentThumbHtml(scent)}</div>
            <div class="scent-info">
                <div class="scent-name-row">
                    <span class="scent-name">${escapeHtml(scent.name)}</span>
                    ${statusBadge}
                </div>
                ${subtitle ? `<div class="scent-subtitle">${escapeHtml(subtitle)}</div>` : ''}
                ${starsHtml(scent.rating, 'small')}
                ${impression ? `<div class="scent-impression">${escapeHtml(impression)}</div>` : ''}
                ${meta.length ? `<div class="scent-meta">${meta.join(' · ')}</div>` : ''}
            </div>
        </div>
    `;
}

// ---- Detail: rating, impression, and the journal --------------------------

async function openScentDetail(scentId) {
    let scent;
    try {
        scent = await api(`/scents/${scentId}`);
    } catch (err) {
        toast(err.message, 'error');
        return;
    }

    const entries = scent.notes || [];
    const subtitle = scentSubtitle(scent);

    const pyramid = [
        ['Top', scent.notes_top],
        ['Heart', scent.notes_heart],
        ['Base', scent.notes_base]
    ].filter(([, notes]) => notes && notes.length);

    const pyramidHtml = pyramid.length ? `
        <div class="scent-pyramid">
            ${pyramid.map(([label, notes]) => `
                <div class="pyramid-row">
                    <span class="pyramid-label">${label}</span>
                    <span class="pyramid-notes">${notes.map(n => `<span class="chip small">${escapeHtml(n)}</span>`).join('')}</span>
                </div>
            `).join('')}
        </div>
    ` : '';

    const facts = [];
    if (scent.family) facts.push(['Family', scent.family]);
    if (scent.sillage) facts.push(['Sillage', scent.sillage]);
    if (scent.time_of_day && scent.time_of_day !== 'any') facts.push(['Best', scent.time_of_day]);
    if (scent.longevity_hours) facts.push(['Longevity', `${scent.longevity_hours}h`]);
    if (scent.size_ml) {
        const left = scent.remaining_pct !== null && scent.remaining_pct !== undefined
            ? ` (${scent.remaining_pct}% left)` : '';
        facts.push(['Bottle', `${scent.size_ml}ml${left}`]);
    }
    if (scent.paid_price) facts.push(['Paid', formatCurrency(scent.paid_price)]);
    if (scent.lifetime_wears) facts.push(['Worn', `${scent.lifetime_wears}x`]);
    if (scent.cost_per_wear) facts.push(['Per wear', formatCurrency(scent.cost_per_wear)]);
    if (scent.last_worn) facts.push(['Last worn', formatDate(scent.last_worn)]);

    const factsHtml = facts.length ? `
        <div class="scent-facts">
            ${facts.map(([k, v]) => `<div class="scent-fact"><span class="fact-key">${escapeHtml(k)}</span><span class="fact-value">${escapeHtml(v)}</span></div>`).join('')}
        </div>
    ` : '';

    const entriesHtml = entries.length
        ? entries.map(entry => `
            <div class="journal-entry" data-note-id="${entry.id}">
                <div class="journal-entry-head">
                    <span class="journal-date">${formatDate(entry.date)}</span>
                    ${entry.rating ? starsHtml(entry.rating, 'small') : ''}
                    ${entry.sprays ? `<span class="journal-sprays">${entry.sprays} spray${entry.sprays === 1 ? '' : 's'}</span>` : ''}
                    <button class="journal-delete" data-note-id="${entry.id}" title="Delete entry">&times;</button>
                </div>
                ${entry.note ? `<div class="journal-note">${escapeHtml(entry.note)}</div>` : ''}
            </div>
        `).join('')
        : '<div class="journal-empty">No entries yet. Write the first one below.</div>';

    const seasonTags = scent.season_tags || [];
    const vibeTags = scent.vibe_tags || [];

    openModal(`
        <div class="modal-header">
            <span class="modal-title">${escapeHtml(scent.name)}</span>
            <button class="modal-close" onclick="closeModal()">&times;</button>
        </div>
        <div class="modal-body">
            <div class="scent-detail-head">
                <div class="scent-detail-thumb">${scentThumbHtml(scent)}</div>
                <div class="scent-detail-title">
                    ${subtitle ? `<div class="scent-subtitle">${escapeHtml(subtitle)}</div>` : ''}
                    <div class="scent-detail-status">${escapeHtml(SCENT_STATUSES.find(s => s.value === (scent.status || 'owned'))?.label || '')}</div>
                </div>
            </div>

            <div class="form-group">
                <label class="form-label">Your rating</label>
                ${starPickerHtml('scent-detail-rating', scent.rating)}
                <div class="form-hint">Tap to rate — saves immediately</div>
            </div>

            <div class="form-group">
                <label class="form-label">Impression</label>
                <textarea class="form-textarea" id="scent-impression" rows="3"
                          placeholder="How does it smell on you? When would you wear it?">${escapeHtml(scent.impression || '')}</textarea>
                <button class="btn btn-sm btn-outline mt-sm" id="save-impression-btn">Save impression</button>
            </div>

            ${pyramidHtml}
            ${(seasonTags.length || vibeTags.length) ? `
                <div class="chip-row">${renderTagChips([...seasonTags, ...vibeTags], true)}</div>
            ` : ''}
            ${factsHtml}

            <div class="journal-section">
                <div class="journal-header">Journal</div>
                <div id="journal-entries">${entriesHtml}</div>

                <div class="journal-add">
                    <textarea class="form-textarea" id="new-note-text" rows="2"
                              placeholder="Add an entry — how it wore today, second thoughts, where you tried it..."></textarea>
                    <div class="journal-add-row">
                        ${starPickerHtml('new-note-rating', 0)}
                    </div>
                    <div class="journal-add-row">
                        <label class="journal-inline-label">Date</label>
                        <input type="date" class="form-input" id="new-note-date" value="${localToday()}">
                        <label class="journal-inline-label">Sprays</label>
                        <input type="number" class="form-input journal-sprays-input" id="new-note-sprays"
                               min="0" max="20" value="0">
                    </div>
                    <div class="form-hint">Sprays above zero logs it as worn and draws down the bottle.</div>
                    <button class="btn btn-primary btn-block mt-sm" id="add-note-btn">Add entry</button>
                </div>
            </div>
        </div>
        <div class="modal-footer">
            <button class="btn btn-outline" id="edit-scent-btn">Edit</button>
            <button class="btn btn-danger" id="delete-scent-btn">Delete</button>
        </div>
    `, true);

    setupStarPicker('scent-detail-rating');
    setupStarPicker('new-note-rating');

    const refresh = async () => {
        state.scents = await api(`/scents?sort=${encodeURIComponent(state.scentFilters.sort)}`);
        state.scentSuggestion = null;   // today's pick may have changed
    };

    // Rating saves on tap. Rating something is the single most common action
    // here, so it should not need a separate Save press.
    document.getElementById('scent-detail-rating').addEventListener('click', async (e) => {
        if (!e.target.closest('.star') && !e.target.closest('.star-clear')) return;
        try {
            await api(`/scents/${scent.id}`, {
                method: 'PATCH',
                body: { rating: readStarPicker('scent-detail-rating') }
            });
            await refresh();
        } catch (err) {
            toast(err.message, 'error');
        }
    });

    document.getElementById('save-impression-btn').addEventListener('click', async () => {
        try {
            await api(`/scents/${scent.id}`, {
                method: 'PATCH',
                body: { impression: document.getElementById('scent-impression').value }
            });
            await refresh();
            toast('Impression saved');
        } catch (err) {
            toast(err.message, 'error');
        }
    });

    document.getElementById('add-note-btn').addEventListener('click', async () => {
        const note = document.getElementById('new-note-text').value.trim();
        const rating = readStarPicker('new-note-rating');
        const sprays = parseInt(document.getElementById('new-note-sprays').value) || 0;
        const date = document.getElementById('new-note-date').value || localToday();

        if (!note && !rating && !sprays) {
            toast('Write something, rate it, or log a spray', 'error');
            return;
        }

        try {
            await api(`/scents/${scent.id}/notes`, {
                method: 'POST',
                body: { note, rating, sprays, date }
            });
            await refresh();
            toast('Entry added');
            openScentDetail(scent.id);
        } catch (err) {
            toast(err.message, 'error');
        }
    });

    document.getElementById('journal-entries').addEventListener('click', async (e) => {
        const btn = e.target.closest('.journal-delete');
        if (!btn) return;
        if (!confirm('Delete this journal entry?')) return;
        try {
            await api(`/scents/${scent.id}/notes/${btn.dataset.noteId}`, { method: 'DELETE' });
            await refresh();
            toast('Entry deleted');
            openScentDetail(scent.id);
        } catch (err) {
            toast(err.message, 'error');
        }
    });

    document.getElementById('edit-scent-btn').addEventListener('click', () => {
        openScentModal(scent);
    });

    document.getElementById('delete-scent-btn').addEventListener('click', async () => {
        if (!confirm(`Delete ${scent.name} and all its journal entries? This cannot be undone.`)) return;
        try {
            await api(`/scents/${scent.id}`, { method: 'DELETE' });
            closeModal();
            toast('Scent deleted');
            renderClosetView(document.getElementById('main-content'));
        } catch (err) {
            toast(err.message, 'error');
        }
    });
}

// ---- Add / edit form ------------------------------------------------------

function openScentModal(scent) {
    const isNew = !scent;
    const seasonTags = state.settings?.season_tags || [];
    const vibeTags = state.settings?.vibe_tags || [];
    const families = state.settings?.fragrance_families || [];

    const statusOptions = SCENT_STATUSES.map(s =>
        `<option value="${s.value}" ${(scent?.status || 'owned') === s.value ? 'selected' : ''}>${s.label}</option>`
    ).join('');

    const concentrationOptions = SCENT_CONCENTRATIONS.map(c =>
        `<option value="${c}" ${(scent?.concentration || '') === c ? 'selected' : ''}>${c ? c.toUpperCase() : '—'}</option>`
    ).join('');

    const familyOptions = ['', ...families].map(f =>
        `<option value="${escapeHtml(f)}" ${(scent?.family || '') === f ? 'selected' : ''}>${f || '—'}</option>`
    ).join('');

    const sillageOptions = SCENT_SILLAGES.map(s =>
        `<option value="${s}" ${(scent?.sillage || 'moderate') === s ? 'selected' : ''}>${s}</option>`
    ).join('');

    const timeOptions = SCENT_TIMES.map(t =>
        `<option value="${t}" ${(scent?.time_of_day || 'any') === t ? 'selected' : ''}>${t}</option>`
    ).join('');

    const seasonChipsHtml = seasonTags.map(t =>
        `<span class="chip ${scent?.season_tags?.includes(t) ? 'active' : ''}" data-tag="${escapeHtml(t)}">${escapeHtml(t)}</span>`
    ).join('');

    const vibeChipsHtml = vibeTags.map(t =>
        `<span class="chip ${scent?.vibe_tags?.includes(t) ? 'active' : ''}" data-tag="${escapeHtml(t)}">${escapeHtml(t)}</span>`
    ).join('');

    const houseOptions = datalistOptionsHtml(
        Array.from(new Set((state.scents || []).map(s => s.house).filter(Boolean))).sort()
    );

    openModal(`
        <div class="modal-header">
            <span class="modal-title">${isNew ? 'Add Scent' : 'Edit Scent'}</span>
            <button class="modal-close" onclick="closeModal()">&times;</button>
        </div>
        <div class="modal-body">
            <form id="scent-form">
                <div class="form-group">
                    <label class="form-label">Name *</label>
                    <input type="text" class="form-input" name="name" required
                           value="${escapeHtml(scent?.name || '')}" placeholder="e.g. Bleu de Chanel">
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label">House</label>
                        <input type="text" class="form-input" name="house" list="scent-house-options"
                               value="${escapeHtml(scent?.house || '')}">
                        <datalist id="scent-house-options">${houseOptions}</datalist>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Status</label>
                        <select class="form-select" name="status">${statusOptions}</select>
                    </div>
                </div>

                <div class="form-group">
                    <label class="form-label">Rating</label>
                    ${starPickerHtml('scent-form-rating', scent?.rating)}
                </div>
                <div class="form-group">
                    <label class="form-label">Impression</label>
                    <textarea class="form-textarea" name="impression" rows="3"
                              placeholder="What did you think? Opening, dry-down, where it fits.">${escapeHtml(scent?.impression || '')}</textarea>
                </div>

                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label">Family</label>
                        <select class="form-select" name="family">${familyOptions}</select>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Concentration</label>
                        <select class="form-select" name="concentration">${concentrationOptions}</select>
                    </div>
                </div>

                <div class="form-group">
                    <label class="form-label">Notes — top</label>
                    <input type="text" class="form-input" name="notes_top"
                           value="${escapeHtml((scent?.notes_top || []).join(', '))}"
                           placeholder="bergamot, grapefruit">
                </div>
                <div class="form-group">
                    <label class="form-label">Notes — heart</label>
                    <input type="text" class="form-input" name="notes_heart"
                           value="${escapeHtml((scent?.notes_heart || []).join(', '))}"
                           placeholder="lavender, jasmine">
                </div>
                <div class="form-group">
                    <label class="form-label">Notes — base</label>
                    <input type="text" class="form-input" name="notes_base"
                           value="${escapeHtml((scent?.notes_base || []).join(', '))}"
                           placeholder="sandalwood, amber">
                    <div class="form-hint">Comma separated</div>
                </div>

                <div class="form-group">
                    <label class="form-label">Season</label>
                    <div class="chip-row" id="scent-season-picker">${seasonChipsHtml}</div>
                </div>
                <div class="form-group">
                    <label class="form-label">Occasion</label>
                    <div class="chip-row" id="scent-vibe-picker">${vibeChipsHtml}</div>
                    <div class="form-hint">Untagged means it's suggested for anything.</div>
                </div>

                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label">Sillage</label>
                        <select class="form-select" name="sillage">${sillageOptions}</select>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Best for</label>
                        <select class="form-select" name="time_of_day">${timeOptions}</select>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label">Bottle (ml)</label>
                        <input type="number" step="1" class="form-input" name="size_ml"
                               value="${scent?.size_ml || ''}">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Paid</label>
                        <input type="number" step="0.01" class="form-input" name="paid_price"
                               value="${scent?.paid_price || ''}">
                    </div>
                </div>
                ${!isNew && scent?.size_ml ? `
                    <div class="form-group">
                        <label class="form-label">Remaining (ml)</label>
                        <input type="number" step="0.1" class="form-input" name="remaining_ml"
                               value="${scent?.remaining_ml ?? ''}">
                        <div class="form-hint">Corrects the estimate if it has drifted from the real bottle.</div>
                    </div>
                ` : ''}

                <div class="form-group">
                    <label class="form-label">Longevity (hours)</label>
                    <input type="number" step="0.5" class="form-input" name="longevity_hours"
                           value="${scent?.longevity_hours || ''}">
                </div>

                <div class="form-group">
                    <label class="form-label">${scent?.photo ? 'Replace photo' : 'Photo'}</label>
                    <div class="file-input-wrapper">
                        <input type="file" class="file-input" accept="image/*" id="scent-photo-input">
                        <div class="file-input-btn"><span>Tap to take or choose photo</span></div>
                    </div>
                    <img class="file-preview hidden" id="scent-photo-preview">
                </div>
            </form>
        </div>
        <div class="modal-footer">
            ${scent?.photo ? '<button class="btn btn-outline" id="remove-scent-photo-btn">Remove photo</button>' : ''}
            <button class="btn btn-primary" id="save-scent-btn">Save</button>
        </div>
    `, true);

    setupStarPicker('scent-form-rating');

    ['scent-season-picker', 'scent-vibe-picker'].forEach(id => {
        document.getElementById(id)?.addEventListener('click', (e) => {
            const chip = e.target.closest('.chip');
            if (chip) chip.classList.toggle('active');
        });
    });

    document.getElementById('scent-photo-input').addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (!file) return;
        const preview = document.getElementById('scent-photo-preview');
        preview.src = URL.createObjectURL(file);
        preview.classList.remove('hidden');
    });

    document.getElementById('remove-scent-photo-btn')?.addEventListener('click', async () => {
        try {
            await api(`/scents/${scent.id}/photo`, { method: 'DELETE' });
            closeModal();
            toast('Photo removed');
            renderClosetView(document.getElementById('main-content'));
        } catch (err) {
            toast(err.message, 'error');
        }
    });

    document.getElementById('save-scent-btn').addEventListener('click', async () => {
        const form = document.getElementById('scent-form');
        const formData = new FormData(form);

        const name = (formData.get('name') || '').trim();
        if (!name) {
            toast('Name is required', 'error');
            return;
        }

        const splitNotes = (value) =>
            (value || '').split(',').map(n => n.trim()).filter(Boolean);

        const data = {
            name,
            house: formData.get('house') || '',
            status: formData.get('status') || 'owned',
            rating: readStarPicker('scent-form-rating'),
            impression: formData.get('impression') || '',
            family: formData.get('family') || '',
            concentration: formData.get('concentration') || '',
            notes_top: splitNotes(formData.get('notes_top')),
            notes_heart: splitNotes(formData.get('notes_heart')),
            notes_base: splitNotes(formData.get('notes_base')),
            sillage: formData.get('sillage') || 'moderate',
            time_of_day: formData.get('time_of_day') || 'any',
            size_ml: parseFloat(formData.get('size_ml')) || 0,
            paid_price: parseFloat(formData.get('paid_price')) || 0,
            longevity_hours: parseFloat(formData.get('longevity_hours')) || 0,
            season_tags: Array.from(document.querySelectorAll('#scent-season-picker .chip.active')).map(el => el.dataset.tag),
            vibe_tags: Array.from(document.querySelectorAll('#scent-vibe-picker .chip.active')).map(el => el.dataset.tag)
        };

        const remainingRaw = formData.get('remaining_ml');
        if (remainingRaw !== null && remainingRaw !== '') {
            data.remaining_ml = parseFloat(remainingRaw) || 0;
        }

        try {
            const saved = isNew
                ? await api('/scents', { method: 'POST', body: data })
                : await api(`/scents/${scent.id}`, { method: 'PATCH', body: data });

            const photoInput = document.getElementById('scent-photo-input');
            if (photoInput.files[0]) {
                const photoForm = new FormData();
                photoForm.append('file', photoInput.files[0]);
                await api(`/scents/${saved.id}/photo`, { method: 'POST', body: photoForm });
                // The filename never changes, so the browser would keep serving
                // the previous bottle photo without a bust token.
                state.photoBust[`scent-${saved.id}`] = Date.now();
            }

            state.scentSuggestion = null;
            closeModal();
            toast(isNew ? 'Scent added' : 'Scent updated');
            renderClosetView(document.getElementById('main-content'));
        } catch (err) {
            toast(err.message, 'error');
        }
    });
}

// ---- Cross-scent journal feed --------------------------------------------

async function openScentJournalModal() {
    openModal(`
        <div class="modal-header">
            <span class="modal-title">Scent Journal</span>
            <button class="modal-close" onclick="closeModal()">&times;</button>
        </div>
        <div class="modal-body"><div class="flex-center"><div class="spinner"></div></div></div>
    `, true);

    let entries;
    try {
        entries = await api('/scents/journal/recent?limit=50');
    } catch (err) {
        toast(err.message, 'error');
        closeModal();
        return;
    }

    const body = document.querySelector('#modal-container .modal-body');
    if (!body) return;

    if (entries.length === 0) {
        body.innerHTML = '<div class="empty-state"><div class="empty-state-text">No journal entries yet</div></div>';
        return;
    }

    body.innerHTML = entries.map(entry => `
        <div class="journal-entry feed" data-scent-id="${entry.fragrance_id}">
            <div class="journal-entry-head">
                <span class="journal-scent-name">${escapeHtml(entry.scent_name)}</span>
                <span class="journal-date">${formatDate(entry.date)}</span>
                ${entry.rating ? starsHtml(entry.rating, 'small') : ''}
            </div>
            ${entry.note ? `<div class="journal-note">${escapeHtml(entry.note)}</div>` : ''}
        </div>
    `).join('');

    body.querySelectorAll('.journal-entry.feed').forEach(el => {
        el.addEventListener('click', () => openScentDetail(parseInt(el.dataset.scentId)));
    });
}

// ========================================
// OUTFITS VIEW
// ========================================

async function renderOutfitsView(container) {
    container.innerHTML = '<div class="flex-center"><div class="spinner"></div></div>';

    try {
        const [, , outfits, pending] = await Promise.all([
            loadSettings(),
            loadActiveTrip(),
            api('/outfits'),
            api('/ai/pending'),
            // AI provider status - fetch once per session
            state.aiStatus
                ? Promise.resolve()
                : api('/ai/status')
                    .then(s => { state.aiStatus = s; })
                    .catch(() => { state.aiStatus = {}; }),
        ]);
        state.outfits = outfits;
        state.pendingOutfits = pending;
    } catch (err) {
        container.innerHTML = `<div class="empty-state"><div class="empty-state-text">Error: ${escapeHtml(err.message)}</div></div>`;
        return;
    }

    const seasonTags = ['', ...(state.settings?.season_tags || [])];
    const vibeTags = ['', ...(state.settings?.vibe_tags || [])];

    let filtered = state.outfits;

    // Vacation mode filtering (unless "Show all" toggled)
    if (state.activeTrip && !state.outfitShowAll) {
        const tripItemIds = new Set(state.activeTrip.item_ids || []);
        filtered = filtered.filter(o => {
            // Outfit is included if all its items are in trip
            const itemIds = (o.items || []).map(item => item.id);
            return itemIds.every(id => tripItemIds.has(id));
        });
    }

    if (state.outfitFilters.season) {
        filtered = filtered.filter(o => o.season_tags?.includes(state.outfitFilters.season));
    }
    if (state.outfitFilters.vibe) {
        filtered = filtered.filter(o => o.vibe_tags?.includes(state.outfitFilters.vibe));
    }
    if (state.outfitFilters.availableOnly) {
        filtered = filtered.filter(o => o.available);
    }

    const seasonChipsHtml = seasonTags.map(t =>
        `<span class="chip ${state.outfitFilters.season === t ? 'active' : ''}" data-season="${escapeHtml(t)}">${t || 'All Seasons'}</span>`
    ).join('');

    const vibeChipsHtml = vibeTags.map(t =>
        `<span class="chip ${state.outfitFilters.vibe === t ? 'active' : ''}" data-vibe="${escapeHtml(t)}">${t || 'All Vibes'}</span>`
    ).join('');

    const outfitsHtml = filtered.length === 0
        ? '<div class="empty-state"><div class="empty-state-text">No outfits found</div></div>'
        : filtered.map(o => renderOutfitCard(o)).join('');

    const pendingHtml = state.pendingOutfits.length > 0 ? `
        <div class="pending-queue">
            <h3 style="margin-bottom: 16px;">Pending AI Outfits</h3>
            ${state.pendingOutfits.map(renderPendingOutfitCard).join('')}
        </div>
    ` : '';

    let vacationNoteHtml = '';
    if (state.activeTrip && !state.outfitShowAll) {
        vacationNoteHtml = `<div class="inline-note">Showing packed items only · <span class="link-text" id="outfit-show-all">Show all</span></div>`;
    } else if (state.activeTrip && state.outfitShowAll) {
        vacationNoteHtml = `<div class="inline-note">Showing all outfits · <span class="link-text" id="outfit-show-all">Hide unpacked</span></div>`;
    }

    container.innerHTML = `
        ${renderVacationBanner()}
        <div class="chip-row scrollable" id="season-filter">${seasonChipsHtml}</div>
        <div class="chip-row scrollable" id="vibe-filter">${vibeChipsHtml}</div>
        ${vacationNoteHtml}
        <div class="chip-row">
            <span class="chip ${state.outfitFilters.availableOnly ? 'active' : ''}" id="available-toggle">Available Only</span>
        </div>
        <div id="outfits-list">${outfitsHtml}</div>

        <div class="ai-section">
            <div class="ai-section-title">Generate Outfits</div>
            <div class="ai-controls">
                <div class="engine-selector">
                    <span class="chip ${state.aiEngine === 'auto' ? 'active' : ''}" data-engine="auto">Auto</span>
                    ${(state.aiStatus?.anthropic) ? `<span class="chip ${state.aiEngine === 'anthropic' ? 'active' : ''}" data-engine="anthropic">Claude AI</span>` : ''}
                    ${(state.aiStatus?.openai) ? `<span class="chip ${state.aiEngine === 'openai' ? 'active' : ''}" data-engine="openai" title="${escapeHtml(state.aiStatus.openai_model || '')}">Local AI</span>` : ''}
                    <span class="chip ${state.aiEngine === 'local' ? 'active' : ''}" data-engine="local">Rule-based</span>
                </div>
            </div>
            <div class="ai-controls">
                <div class="number-stepper">
                    <button id="ai-minus">-</button>
                    <span id="ai-count">${state.aiGenerateCount}</span>
                    <button id="ai-plus">+</button>
                </div>
                <button class="btn btn-primary" id="ai-generate-btn" ${state.aiGenerating ? 'disabled' : ''}>
                    ${state.aiGenerating ? '<div class="spinner"></div>' : 'Generate'}
                </button>
            </div>
            ${pendingHtml}
        </div>

        <button class="fab" id="add-outfit-btn">+</button>
    `;

    setupVacationBanner(container);

    // Vacation "Show all" toggle
    const showAllBtn = container.querySelector('#outfit-show-all');
    if (showAllBtn) {
        showAllBtn.addEventListener('click', () => {
            state.outfitShowAll = !state.outfitShowAll;
            renderOutfitsView(container);
        });
    }

    // Season filter
    document.getElementById('season-filter').addEventListener('click', (e) => {
        const chip = e.target.closest('.chip');
        if (!chip) return;
        state.outfitFilters.season = chip.dataset.season;
        renderOutfitsView(container);
    });

    // Vibe filter
    document.getElementById('vibe-filter').addEventListener('click', (e) => {
        const chip = e.target.closest('.chip');
        if (!chip) return;
        state.outfitFilters.vibe = chip.dataset.vibe;
        renderOutfitsView(container);
    });

    // Available toggle
    document.getElementById('available-toggle').addEventListener('click', () => {
        state.outfitFilters.availableOnly = !state.outfitFilters.availableOnly;
        renderOutfitsView(container);
    });

    // Outfit cards
    container.querySelectorAll('.outfit-card').forEach(card => {
        card.addEventListener('click', () => {
            const outfitId = parseInt(card.dataset.outfitId);
            const outfit = state.outfits.find(o => o.id === outfitId);
            if (outfit) openOutfitModal(outfit);
        });
    });

    // Add outfit
    document.getElementById('add-outfit-btn').addEventListener('click', () => {
        openOutfitModal(null);
    });

    // Engine selector
    container.querySelectorAll('.engine-selector .chip').forEach(chip => {
        chip.addEventListener('click', () => {
            state.aiEngine = chip.dataset.engine;
            renderOutfitsView(container);
        });
    });

    // AI stepper
    document.getElementById('ai-minus').addEventListener('click', () => {
        if (state.aiGenerateCount > 1) {
            state.aiGenerateCount--;
            document.getElementById('ai-count').textContent = state.aiGenerateCount;
        }
    });
    document.getElementById('ai-plus').addEventListener('click', () => {
        if (state.aiGenerateCount < 10) {
            state.aiGenerateCount++;
            document.getElementById('ai-count').textContent = state.aiGenerateCount;
        }
    });

    // AI generate
    document.getElementById('ai-generate-btn').addEventListener('click', async () => {
        state.aiGenerating = true;
        renderOutfitsView(container);

        try {
            const result = await api('/ai/generate', {
                method: 'POST',
                body: { count: state.aiGenerateCount, engine: state.aiEngine }
            });
            state.pendingOutfits = await api('/ai/pending');

            // Show which engine was used
            if (result.length > 0 && result[0].engine_used) {
                const engineLabels = {
                    ai: 'Claude AI',
                    anthropic: 'Claude AI',
                    openai: 'local AI',
                    local: 'rule-based',
                };
                const engineLabel = engineLabels[result[0].engine_used] || result[0].engine_used;
                toast(`${result.length} outfit(s) generated using ${engineLabel}!`);
            } else if (result.length === 0) {
                toast('No new outfits could be generated (all combinations taken)', 'error');
            } else {
                toast('Outfits generated!');
            }
        } catch (err) {
            toast(err.message, 'error');
        }

        state.aiGenerating = false;
        renderOutfitsView(container);
    });

    // Pending approve/reject
    container.querySelectorAll('.approve-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const id = parseInt(btn.dataset.id);
            try {
                await api(`/ai/${id}/approve`, { method: 'POST' });
                toast('Outfit approved!');
                renderOutfitsView(container);
            } catch (err) {
                toast(err.message, 'error');
            }
        });
    });

    container.querySelectorAll('.reject-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const id = parseInt(btn.dataset.id);
            try {
                await api(`/ai/${id}/reject`, { method: 'POST' });
                toast('Outfit rejected');
                renderOutfitsView(container);
            } catch (err) {
                toast(err.message, 'error');
            }
        });
    });
}

function renderPendingOutfitCard(outfit) {
    const thumbsHtml = (outfit.items || []).map(item => `
        <div class="item-thumb">${getItemThumbHtml(item)}</div>
    `).join('');

    return `
        <div class="pending-outfit">
            <div class="outfit-name">${escapeHtml(outfit.name)}</div>
            <div class="outfit-thumbnails">${thumbsHtml}</div>
            ${outfit.ai_note ? `<div class="outfit-note">${escapeHtml(outfit.ai_note)}</div>` : ''}
            <div class="pending-actions">
                <button class="btn btn-primary btn-sm approve-btn" data-id="${outfit.id}">Approve</button>
                <button class="btn btn-secondary btn-sm reject-btn" data-id="${outfit.id}">Reject</button>
            </div>
        </div>
    `;
}

async function openOutfitModal(outfit) {
    const isNew = !outfit;
    const title = isNew ? 'New Outfit' : 'Edit Outfit';

    // Load items for picker
    let allItems = [];
    try {
        allItems = await api('/items');
    } catch (err) {
        toast(err.message, 'error');
        return;
    }

    const selectedIds = new Set((outfit?.items || []).map(i => i.id));
    const seasonTags = state.settings?.season_tags || [];
    const vibeTags = state.settings?.vibe_tags || [];
    const categories = state.settings?.categories || [];
    const categoryNames = categories.map(c => typeof c === 'string' ? c : c.name);

    const seasonChipsHtml = seasonTags.map(t => {
        const selected = outfit?.season_tags?.includes(t);
        return `<span class="chip ${selected ? 'active' : ''}" data-tag="${escapeHtml(t)}" data-type="season">${escapeHtml(t)}</span>`;
    }).join('');

    const vibeChipsHtml = vibeTags.map(t => {
        const selected = outfit?.vibe_tags?.includes(t);
        return `<span class="chip ${selected ? 'active' : ''}" data-tag="${escapeHtml(t)}" data-type="vibe">${escapeHtml(t)}</span>`;
    }).join('');

    // Group items by category
    const grouped = {};
    categoryNames.forEach(c => grouped[c] = []);
    allItems.forEach(item => {
        if (grouped[item.category]) {
            grouped[item.category].push(item);
        } else {
            grouped[item.category] = [item];
        }
    });

    let itemPickerHtml = '';
    Object.entries(grouped).forEach(([cat, items]) => {
        if (items.length === 0) return;
        itemPickerHtml += `<div style="font-weight: 600; margin: 16px 0 8px; color: var(--text-secondary);">${escapeHtml(cat)}</div>`;
        itemPickerHtml += items.map(item => `
            <div class="list-item selectable ${selectedIds.has(item.id) ? 'selected' : ''}" data-item-id="${item.id}">
                <div class="list-item-photo">${getItemThumbHtml(item)}</div>
                <div class="list-item-content">
                    <div class="list-item-title">#${item.number} ${escapeHtml(item.name)}</div>
                    <div class="list-item-subtitle">${item.status}</div>
                </div>
            </div>
        `).join('');
    });

    // Outfit preview photo section for existing outfits
    let outfitPreviewHtml = '';
    if (outfit) {
        const previewSrc = outfit.photo || (outfit.has_collage ? `/api/outfits/${outfit.id}/collage` : '');
        if (previewSrc) {
            outfitPreviewHtml = `
                <div class="form-group">
                    <label class="form-label">Preview Photo</label>
                    <div class="outfit-modal-preview">
                        <img src="${escapeHtml(previewSrc)}" alt="Outfit preview" class="outfit-preview-large" onclick="openFullScreenImage('${escapeHtml(previewSrc)}')">
                    </div>
                    <div class="outfit-photo-actions">
                        <label class="btn btn-secondary btn-sm">
                            <input type="file" class="hidden" accept="image/*" id="outfit-photo-input">
                            Replace Photo
                        </label>
                        ${outfit.photo ? '<button class="btn btn-outline btn-sm" id="remove-outfit-photo-btn">Remove Photo</button>' : ''}
                    </div>
                </div>
            `;
        } else {
            outfitPreviewHtml = `
                <div class="form-group">
                    <label class="form-label">Preview Photo</label>
                    <label class="btn btn-secondary btn-block">
                        <input type="file" class="hidden" accept="image/*" id="outfit-photo-input">
                        Add Preview Photo
                    </label>
                </div>
            `;
        }
    }

    openModal(`
        <div class="modal-header">
            <span class="modal-title">${title}</span>
            <button class="modal-close" onclick="closeModal()">&times;</button>
        </div>
        <div class="modal-body">
            ${outfitPreviewHtml}
            <div class="form-group">
                <label class="form-label">Name</label>
                <input type="text" class="form-input" id="outfit-name" value="${escapeHtml(outfit?.name || '')}" required>
            </div>
            <div class="form-group">
                <label class="form-label">Season Tags</label>
                <div class="chip-row" id="outfit-season-tags">${seasonChipsHtml}</div>
            </div>
            <div class="form-group">
                <label class="form-label">Vibe Tags</label>
                <div class="chip-row" id="outfit-vibe-tags">${vibeChipsHtml}</div>
            </div>
            <div class="form-group">
                <label class="form-label">Selected Items</label>
                <div class="chip-row" id="selected-items-display"></div>
            </div>
            <div class="form-group">
                <label class="form-label">Pick Items</label>
                <div class="search-bar">
                    <input type="text" placeholder="Search..." id="item-picker-search">
                </div>
                <div id="item-picker" style="max-height: 300px; overflow-y: auto;">${itemPickerHtml}</div>
            </div>
        </div>
        <div class="modal-footer">
            ${outfit ? `<button class="btn btn-danger" id="delete-outfit-btn">Delete</button>` : ''}
            <button class="btn btn-primary" id="save-outfit-btn">Save</button>
        </div>
    `, true);

    // Outfit photo upload
    document.getElementById('outfit-photo-input')?.addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (!file || !outfit) return;

        const formData = new FormData();
        formData.append('file', file);

        try {
            await api(`/outfits/${outfit.id}/photo`, { method: 'POST', body: formData });
            closeModal();
            toast('Outfit photo updated!');
            renderOutfitsView(document.getElementById('main-content'));
        } catch (err) {
            toast(err.message, 'error');
        }
    });

    // Remove outfit photo
    document.getElementById('remove-outfit-photo-btn')?.addEventListener('click', async () => {
        if (!confirm('Remove outfit preview photo?')) return;
        try {
            await api(`/outfits/${outfit.id}/photo`, { method: 'DELETE' });
            closeModal();
            toast('Photo removed');
            renderOutfitsView(document.getElementById('main-content'));
        } catch (err) {
            toast(err.message, 'error');
        }
    });

    const selectedSet = new Set(selectedIds);

    function updateSelectedDisplay() {
        const display = document.getElementById('selected-items-display');
        const selected = allItems.filter(i => selectedSet.has(i.id));
        display.innerHTML = selected.map(i =>
            `<span class="chip small">#${i.number} ${escapeHtml(i.name)}</span>`
        ).join('') || '<span style="color: var(--text-muted);">None selected</span>';
    }

    updateSelectedDisplay();

    // Tag pickers
    ['outfit-season-tags', 'outfit-vibe-tags'].forEach(id => {
        document.getElementById(id)?.addEventListener('click', (e) => {
            const chip = e.target.closest('.chip');
            if (chip) chip.classList.toggle('active');
        });
    });

    // Item picker
    document.getElementById('item-picker').addEventListener('click', (e) => {
        const listItem = e.target.closest('.list-item');
        if (!listItem) return;
        const itemId = parseInt(listItem.dataset.itemId);
        if (selectedSet.has(itemId)) {
            selectedSet.delete(itemId);
            listItem.classList.remove('selected');
        } else {
            selectedSet.add(itemId);
            listItem.classList.add('selected');
        }
        updateSelectedDisplay();
    });

    // Item search
    document.getElementById('item-picker-search').addEventListener('input', (e) => {
        const q = e.target.value.toLowerCase();
        document.querySelectorAll('#item-picker .list-item').forEach(el => {
            const text = el.textContent.toLowerCase();
            el.style.display = text.includes(q) ? '' : 'none';
        });
    });

    // Save
    document.getElementById('save-outfit-btn').addEventListener('click', async () => {
        const name = document.getElementById('outfit-name').value.trim();
        if (!name) {
            toast('Name is required', 'error');
            return;
        }

        const seasonTagEls = document.querySelectorAll('#outfit-season-tags .chip.active');
        const vibeTagEls = document.querySelectorAll('#outfit-vibe-tags .chip.active');

        const data = {
            name: name,
            item_ids: Array.from(selectedSet),
            season_tags: Array.from(seasonTagEls).map(el => el.dataset.tag),
            vibe_tags: Array.from(vibeTagEls).map(el => el.dataset.tag)
        };

        try {
            if (isNew) {
                await api('/outfits', { method: 'POST', body: data });
            } else {
                await api(`/outfits/${outfit.id}`, { method: 'PATCH', body: data });
            }
            closeModal();
            toast(isNew ? 'Outfit created!' : 'Outfit updated!');
            renderOutfitsView(document.getElementById('main-content'));
        } catch (err) {
            toast(err.message, 'error');
        }
    });

    // Delete
    document.getElementById('delete-outfit-btn')?.addEventListener('click', async () => {
        if (!confirm('Delete this outfit?')) return;
        try {
            await api(`/outfits/${outfit.id}`, { method: 'DELETE' });
            closeModal();
            toast('Outfit deleted');
            renderOutfitsView(document.getElementById('main-content'));
        } catch (err) {
            toast(err.message, 'error');
        }
    });
}

// ========================================
// LAUNDRY VIEW
// ========================================

async function renderLaundryView(container) {
    container.innerHTML = '<div class="flex-center"><div class="spinner"></div></div>';

    try {
        state.dirtyItems = await api('/laundry/dirty');
    } catch (err) {
        container.innerHTML = `<div class="empty-state"><div class="empty-state-text">Error: ${escapeHtml(err.message)}</div></div>`;
        return;
    }

    if (state.dirtyItems.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">&#127881;</div>
                <div class="empty-state-text">No dirty laundry</div>
            </div>
        `;
        return;
    }

    const itemsHtml = state.dirtyItems.map(item => `
        <div class="laundry-item ${state.laundrySelectMode ? 'selectable' : ''} ${state.laundrySelected.has(item.id) ? 'selected' : ''}" data-item-id="${item.id}">
            ${state.laundrySelectMode ? `<div class="laundry-checkbox ${state.laundrySelected.has(item.id) ? 'checked' : ''}"></div>` : ''}
            <div class="list-item-photo">${getItemThumbHtml(item)}</div>
            <div class="list-item-content">
                <div class="list-item-title">${escapeHtml(item.name)}</div>
                <div class="list-item-subtitle">${item.wears_since_wash} wears since wash</div>
            </div>
        </div>
    `).join('');

    container.innerHTML = `
        <div class="laundry-actions">
            ${state.laundrySelectMode ? `
                <button class="btn btn-secondary" id="cancel-select-btn">Cancel</button>
                <button class="btn btn-primary" id="wash-selected-btn" ${state.laundrySelected.size === 0 ? 'disabled' : ''}>
                    Mark ${state.laundrySelected.size} Washed
                </button>
            ` : `
                <button class="btn btn-outline" id="select-mode-btn">Select Items</button>
                <button class="btn btn-primary" id="wash-all-btn">Everything's Clean</button>
            `}
        </div>
        <div id="laundry-list">${itemsHtml}</div>
    `;

    // Select mode toggle
    document.getElementById('select-mode-btn')?.addEventListener('click', () => {
        state.laundrySelectMode = true;
        state.laundrySelected.clear();
        renderLaundryView(container);
    });

    document.getElementById('cancel-select-btn')?.addEventListener('click', () => {
        state.laundrySelectMode = false;
        state.laundrySelected.clear();
        renderLaundryView(container);
    });

    // Item selection
    if (state.laundrySelectMode) {
        container.querySelectorAll('.laundry-item').forEach(el => {
            el.addEventListener('click', () => {
                const id = parseInt(el.dataset.itemId);
                if (state.laundrySelected.has(id)) {
                    state.laundrySelected.delete(id);
                } else {
                    state.laundrySelected.add(id);
                }
                renderLaundryView(container);
            });
        });
    }

    // Wash all
    document.getElementById('wash-all-btn')?.addEventListener('click', async () => {
        if (!confirm('Mark all items as clean?')) return;
        try {
            const result = await api('/laundry', { method: 'POST', body: { mode: 'all' } });
            toast(`${result.washed} items washed!`);
            renderLaundryView(container);
        } catch (err) {
            toast(err.message, 'error');
        }
    });

    // Wash selected
    document.getElementById('wash-selected-btn')?.addEventListener('click', async () => {
        try {
            const result = await api('/laundry', {
                method: 'POST',
                body: { mode: 'select', item_ids: Array.from(state.laundrySelected) }
            });
            state.laundrySelectMode = false;
            state.laundrySelected.clear();
            toast(`${result.washed} items washed!`);
            renderLaundryView(container);
        } catch (err) {
            toast(err.message, 'error');
        }
    });
}

// ========================================
// STATS VIEW
// ========================================

async function renderStatsView(container) {
    container.innerHTML = '<div class="flex-center"><div class="spinner"></div></div>';

    try {
        [state.stats, state.gapsData, state.wearHistory] = await Promise.all([
            api('/stats'),
            api('/analysis/gaps'),
            api(`/wear/history?year=${state.calendarYear}&month=${state.calendarMonth + 1}`)
        ]);
    } catch (err) {
        container.innerHTML = `<div class="empty-state"><div class="empty-state-text">Error: ${escapeHtml(err.message)}</div></div>`;
        return;
    }

    const { totals, items: mostWorn, neglected, total_value, best_cpw, worst_cpw, by_category, by_brand } = state.stats;
    const gaps = state.gapsData;

    const mostWornHtml = mostWorn.slice(0, 10).map(item => `
        <div class="stats-list-item">
            <span>${escapeHtml(item.name)}</span>
            <span>${item.lifetime_wears} wears (${formatCurrency(item.cost_per_wear)}/wear)</span>
        </div>
    `).join('');

    const neglectedHtml = neglected.map(item => `
        <div class="stats-list-item">
            <span>${escapeHtml(item.name)}</span>
            <span>${item.lifetime_wears} wears, last: ${formatDate(item.last_worn)}</span>
        </div>
    `).join('');

    // Value card
    const valueHtml = renderValueCard(total_value, best_cpw, worst_cpw);

    // By category table
    const byCategoryHtml = renderByCategoryTable(by_category);

    // By brand table
    const byBrandHtml = renderByBrandTable(by_brand);

    // Gaps card
    const gapsHtml = renderGapsCard(gaps);

    const calendarHtml = renderCalendar();

    container.innerHTML = `
        <div class="stats-totals">
            <div class="stat-item">
                <div class="stat-value">${totals.items}</div>
                <div class="stat-label">Items</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">${totals.outfits}</div>
                <div class="stat-label">Outfits</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">${totals.wears}</div>
                <div class="stat-label">Total Wears</div>
            </div>
        </div>

        ${valueHtml}

        <div class="stats-section">
            <div class="stats-section-title">Most Worn</div>
            ${mostWornHtml || '<div class="text-muted">No wear data yet</div>'}
        </div>

        <div class="stats-section">
            <div class="stats-section-title">Neglected Items</div>
            ${neglectedHtml || '<div class="text-muted">No neglected items</div>'}
        </div>

        ${byCategoryHtml}
        ${byBrandHtml}
        ${gapsHtml}

        <div class="stats-section">
            <div class="stats-section-title">Wear Calendar</div>
            ${calendarHtml}
        </div>
    `;

    // Calendar navigation
    document.getElementById('cal-prev').addEventListener('click', () => {
        state.calendarMonth--;
        if (state.calendarMonth < 0) {
            state.calendarMonth = 11;
            state.calendarYear--;
        }
        renderStatsView(container);
    });

    document.getElementById('cal-next').addEventListener('click', () => {
        state.calendarMonth++;
        if (state.calendarMonth > 11) {
            state.calendarMonth = 0;
            state.calendarYear++;
        }
        renderStatsView(container);
    });

    // Calendar day clicks
    container.querySelectorAll('.calendar-day.has-event').forEach(day => {
        day.addEventListener('click', () => {
            const dateStr = day.dataset.date;
            showDayWears(dateStr);
        });
    });
}

function renderValueCard(totalValue, bestCpw, worstCpw) {
    const bestItems = (bestCpw || []).slice(0, 5);
    const worstItems = (worstCpw || []).slice(0, 5);

    const bestHtml = bestItems.map(item => `
        <div class="stats-list-item">
            <span>${escapeHtml(item.name)}</span>
            <span>${formatCurrency(item.cost_per_wear)}/wear</span>
        </div>
    `).join('') || '<div class="text-muted">No data</div>';

    const worstHtml = worstItems.map(item => `
        <div class="stats-list-item">
            <span>${escapeHtml(item.name)}</span>
            <span>${formatCurrency(item.cost_per_wear)}/wear</span>
        </div>
    `).join('') || '<div class="text-muted">No data</div>';

    return `
        <div class="stats-section card">
            <div class="stats-section-title">Value</div>
            <div class="stat-value-large">${formatCurrency(totalValue || 0)}</div>
            <div class="text-muted mb-md">Total wardrobe value</div>
            <div class="stats-subsection">
                <div class="stats-subsection-title">Best Cost-Per-Wear</div>
                ${bestHtml}
            </div>
            <div class="stats-subsection">
                <div class="stats-subsection-title">Worst Cost-Per-Wear</div>
                ${worstHtml}
            </div>
        </div>
    `;
}

function renderByCategoryTable(byCategory) {
    if (!byCategory || Object.keys(byCategory).length === 0) {
        return '';
    }

    const rows = Object.entries(byCategory).map(([cat, data]) => `
        <tr>
            <td>${escapeHtml(cat)}</td>
            <td>${data.count || 0}</td>
            <td>${formatCurrency(data.total_value || 0)}</td>
            <td>${data.total_wears || 0}</td>
            <td>${formatCurrency(data.avg_cpw || 0)}</td>
        </tr>
    `).join('');

    return `
        <div class="stats-section">
            <div class="stats-section-title">By Category</div>
            <div class="stats-table-wrapper">
                <table class="stats-table">
                    <thead>
                        <tr>
                            <th>Category</th>
                            <th>Items</th>
                            <th>Value</th>
                            <th>Wears</th>
                            <th>Avg CPW</th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
        </div>
    `;
}

function renderByBrandTable(byBrand) {
    if (!byBrand || Object.keys(byBrand).length === 0) {
        return '';
    }

    const rows = Object.entries(byBrand).map(([brand, data]) => `
        <tr>
            <td>${escapeHtml(brand || 'Unknown')}</td>
            <td>${data.count || 0}</td>
            <td>${formatCurrency(data.total_value || 0)}</td>
            <td>${data.total_wears || 0}</td>
            <td>${formatCurrency(data.avg_cpw || 0)}</td>
        </tr>
    `).join('');

    return `
        <div class="stats-section">
            <div class="stats-section-title">By Brand</div>
            <div class="stats-table-wrapper">
                <table class="stats-table">
                    <thead>
                        <tr>
                            <th>Brand</th>
                            <th>Items</th>
                            <th>Value</th>
                            <th>Wears</th>
                            <th>Avg CPW</th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
        </div>
    `;
}

function renderGapsCard(gaps) {
    if (!gaps) return '';

    const { coverage, flags, bottlenecks } = gaps;

    // Coverage table: rows = categories, cols = seasons
    let coverageHtml = '';
    if (coverage && Object.keys(coverage).length > 0) {
        const seasons = ['spring', 'summer', 'fall', 'winter'];
        const categories = Object.keys(coverage);

        const headerCells = seasons.map(s => `<th>${s.charAt(0).toUpperCase() + s.slice(1)}</th>`).join('');
        const rows = categories.map(cat => {
            const cells = seasons.map(s => {
                const count = coverage[cat]?.[s] || 0;
                const cellClass = count === 0 ? 'gap-zero' : '';
                return `<td class="${cellClass}">${count}</td>`;
            }).join('');
            return `<tr><td>${escapeHtml(cat)}</td>${cells}</tr>`;
        }).join('');

        coverageHtml = `
            <div class="stats-subsection">
                <div class="stats-subsection-title">Coverage by Season</div>
                <div class="stats-table-wrapper">
                    <table class="stats-table">
                        <thead>
                            <tr><th>Category</th>${headerCells}</tr>
                        </thead>
                        <tbody>${rows}</tbody>
                    </table>
                </div>
            </div>
        `;
    }

    // Flags
    const flagsHtml = (flags && flags.length > 0)
        ? `<div class="stats-subsection">
            <div class="stats-subsection-title">Flags</div>
            <ul class="gaps-flags">${flags.map(f => `<li>${escapeHtml(f)}</li>`).join('')}</ul>
           </div>`
        : '';

    // Bottlenecks
    const bottlenecksHtml = (bottlenecks && bottlenecks.length > 0)
        ? `<div class="stats-subsection">
            <div class="stats-subsection-title">Bottleneck Items</div>
            ${bottlenecks.map(b => `
                <div class="stats-list-item">
                    <span>${escapeHtml(b.name || b.number)}</span>
                    <span>in ${b.outfit_count} outfits</span>
                </div>
            `).join('')}
           </div>`
        : '';

    if (!coverageHtml && !flagsHtml && !bottlenecksHtml) {
        return '';
    }

    return `
        <div class="stats-section card">
            <div class="stats-section-title">Wardrobe Gaps</div>
            ${coverageHtml}
            ${flagsHtml}
            ${bottlenecksHtml}
        </div>
    `;
}

function renderCalendar() {
    const year = state.calendarYear;
    const month = state.calendarMonth;

    const monthNames = ['January', 'February', 'March', 'April', 'May', 'June',
        'July', 'August', 'September', 'October', 'November', 'December'];

    const firstDay = new Date(year, month, 1);
    const lastDay = new Date(year, month + 1, 0);
    const startDayOfWeek = firstDay.getDay();
    const daysInMonth = lastDay.getDate();

    const today = new Date();
    const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;

    // Build set of dates with events
    const eventDates = new Set();
    state.wearHistory.forEach(e => {
        eventDates.add(e.date);
    });

    let daysHtml = '';

    // Previous month's trailing days
    const prevMonth = new Date(year, month, 0);
    const prevMonthDays = prevMonth.getDate();
    for (let i = startDayOfWeek - 1; i >= 0; i--) {
        daysHtml += `<button class="calendar-day other-month">${prevMonthDays - i}</button>`;
    }

    // Current month
    for (let d = 1; d <= daysInMonth; d++) {
        const dateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
        const isToday = dateStr === todayStr;
        const hasEvent = eventDates.has(dateStr);

        daysHtml += `<button class="calendar-day ${isToday ? 'today' : ''} ${hasEvent ? 'has-event' : ''}" data-date="${dateStr}">${d}</button>`;
    }

    // Next month's leading days
    const remainingCells = 42 - (startDayOfWeek + daysInMonth);
    for (let i = 1; i <= remainingCells; i++) {
        daysHtml += `<button class="calendar-day other-month">${i}</button>`;
    }

    return `
        <div class="calendar">
            <div class="calendar-header">
                <div class="calendar-nav">
                    <button id="cal-prev">&lt;</button>
                </div>
                <div class="calendar-title">${monthNames[month]} ${year}</div>
                <div class="calendar-nav">
                    <button id="cal-next">&gt;</button>
                </div>
            </div>
            <div class="calendar-weekdays">
                <div class="calendar-weekday">Sun</div>
                <div class="calendar-weekday">Mon</div>
                <div class="calendar-weekday">Tue</div>
                <div class="calendar-weekday">Wed</div>
                <div class="calendar-weekday">Thu</div>
                <div class="calendar-weekday">Fri</div>
                <div class="calendar-weekday">Sat</div>
            </div>
            <div class="calendar-days">${daysHtml}</div>
        </div>
    `;
}

function showDayWears(dateStr) {
    const events = state.wearHistory.filter(e => e.date === dateStr);
    if (events.length === 0) return;

    const eventsHtml = events.map(e => {
        // Ad-hoc events (outfit_name null) display item names
        const isAdHoc = e.outfit_name === null || e.outfit_name === undefined;
        const itemNames = (e.items || []).map(i => escapeHtml(i.name || 'Item #' + i.item_id)).join(', ');
        const title = isAdHoc ? `Ad-hoc: ${itemNames}` : escapeHtml(e.outfit_name);
        const subtitle = isAdHoc ? '' : itemNames;

        // Event photo thumbnail
        const photoHtml = e.photo ? `
            <div class="day-wear-photo" data-photo="${escapeHtml(e.photo)}">
                <img src="${escapeHtml(e.photo)}" alt="Wear photo" loading="lazy">
            </div>
        ` : '';

        return `
            <div class="day-wear-event" data-event-id="${e.id}">
                ${photoHtml}
                <div class="list-item-content">
                    <div class="list-item-title">${title}</div>
                    ${subtitle ? `<div class="list-item-subtitle">${subtitle}</div>` : ''}
                </div>
                <button class="btn btn-sm btn-outline undo-wear-btn" data-event-id="${e.id}">Undo</button>
            </div>
        `;
    }).join('');

    openModal(`
        <div class="modal-header">
            <span class="modal-title">Worn on ${dateStr}</span>
            <button class="modal-close" onclick="closeModal()">&times;</button>
        </div>
        <div class="modal-body">${eventsHtml}</div>
        <div class="modal-footer">
            <button class="btn btn-secondary btn-block" onclick="closeModal()">Close</button>
        </div>
    `);

    // Photo tap handlers for full screen view
    document.querySelectorAll('.day-wear-photo').forEach(el => {
        el.addEventListener('click', () => {
            const photoUrl = el.dataset.photo;
            if (photoUrl) openFullScreenImage(photoUrl);
        });
    });

    // Attach undo handlers
    document.querySelectorAll('.undo-wear-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            const eventId = btn.dataset.eventId;
            if (!confirm('Reverses wear counts and dirty marks. Continue?')) return;

            try {
                const result = await api(`/wear/${eventId}`, { method: 'DELETE' });
                closeModal();
                const reversedCount = result.reversed_items?.length || 0;
                toast(`Wear undone! ${reversedCount} item(s) reversed.`);
                // Refresh stats view
                renderStatsView(document.getElementById('main-content'));
            } catch (err) {
                toast(err.message, 'error');
            }
        });
    });
}

// ========================================
// TRIPS VIEW
// ========================================

async function renderTripsView(container) {
    container.innerHTML = '<div class="flex-center"><div class="spinner"></div></div>';

    try {
        await loadSettings();
        await loadActiveTrip();
        state.trips = await api('/trips');
    } catch (err) {
        container.innerHTML = `<div class="empty-state"><div class="empty-state-text">Error: ${escapeHtml(err.message)}</div></div>`;
        return;
    }

    // If we have a detail view open, render that instead
    if (state.tripDetail) {
        renderTripDetailView(container);
        return;
    }

    const tripsHtml = state.trips.length === 0
        ? '<div class="empty-state"><div class="empty-state-text">No trips yet</div></div>'
        : state.trips.map(trip => renderTripCard(trip)).join('');

    container.innerHTML = `
        ${renderVacationBanner()}
        ${tripsHtml}
        <button class="btn btn-primary btn-block" id="new-trip-btn">+ New Trip</button>
    `;

    setupVacationBanner(container);

    container.querySelectorAll('.trip-card').forEach(card => {
        card.addEventListener('click', async () => {
            const tripId = parseInt(card.dataset.tripId);
            try {
                state.tripDetail = await api(`/trips/${tripId}`);
                renderTripsView(container);
            } catch (err) {
                toast(err.message, 'error');
            }
        });
    });

    document.getElementById('new-trip-btn').addEventListener('click', () => openTripModal());
}

function renderTripCard(trip) {
    const isActive = trip.status === 'active';
    const activeClass = isActive ? 'active' : '';
    const dest = trip.destination ? `${escapeHtml(trip.destination)}` : 'No destination';
    const dates = `${trip.start_date} to ${trip.end_date} (${trip.num_days} days)`;
    const progress = trip.item_count > 0 ? `${trip.packed_count}/${trip.item_count} packed` : '0 items';

    return `
        <div class="trip-card ${activeClass}" data-trip-id="${trip.id}">
            <div class="trip-header">
                <div>
                    <div class="trip-name">${escapeHtml(trip.name)}</div>
                    <div class="trip-destination">${dest}</div>
                </div>
                <span class="badge ${trip.status}">${trip.status}</span>
            </div>
            <div class="trip-dates">${dates}</div>
            <div class="trip-meta">
                <span class="trip-progress">${progress}</span>
            </div>
        </div>
    `;
}

async function renderTripDetailView(container) {
    const trip = state.tripDetail;
    if (!trip) {
        state.tripDetail = null;
        renderTripsView(container);
        return;
    }

    const dest = trip.destination ? `${escapeHtml(trip.destination)}` : '';
    const dates = `${trip.start_date} to ${trip.end_date} (${trip.num_days} days)`;
    const isActive = trip.status === 'active';

    let forecastHtml = '';
    if (trip.forecast && trip.forecast.length > 0) {
        forecastHtml = `
            <div class="forecast-strip">
                ${trip.forecast.map(day => `
                    <div class="forecast-day">
                        <div class="forecast-date">${day.date}</div>
                        <div class="forecast-desc">${escapeHtml(day.description)}</div>
                        <div class="forecast-temp">${day.high_f}° / ${day.low_f}°</div>
                        <div class="forecast-precip">${day.precip_prob}% precip</div>
                    </div>
                `).join('')}
            </div>
        `;
    } else if (trip.forecast_note) {
        forecastHtml = `<div class="inline-note">${escapeHtml(trip.forecast_note)}</div>`;
    }

    const linkedOutfitsHtml = (trip.outfits || []).map(outfit =>
        `<span class="linked-outfit-chip" data-outfit-id="${outfit.id}">
            ${escapeHtml(outfit.name)}
            <span class="remove-btn">&times;</span>
        </span>`
    ).join('');

    // Group items by category
    const categories = state.settings?.categories || [];
    const catNames = categories.map(c => typeof c === 'string' ? c : c.name);
    const grouped = {};
    catNames.forEach(c => grouped[c] = []);
    (trip.items || []).forEach(item => {
        const cat = item.category || 'other';
        if (!grouped[cat]) grouped[cat] = [];
        grouped[cat].push(item);
    });

    let packingListHtml = '';
    Object.entries(grouped).forEach(([cat, items]) => {
        if (items.length === 0) return;
        packingListHtml += `<div class="packing-category">${escapeHtml(cat)}</div>`;
        packingListHtml += items.map(item => `
            <div class="packing-item">
                <div class="packing-checkbox ${item.packed ? 'checked' : ''}" data-item-id="${item.id}"></div>
                <div class="packing-item-name">#${item.number} ${escapeHtml(item.name)}${item.color ? ' - ' + escapeHtml(item.color) : ''}</div>
                ${item.source !== 'manual' ? `<span class="packing-item-source">${item.source}</span>` : ''}
                <button class="packing-item-remove" data-item-id="${item.id}">&times;</button>
            </div>
        `).join('');
    });

    const packedCount = (trip.items || []).filter(i => i.packed).length;
    const totalCount = (trip.items || []).length;
    const progressPct = totalCount > 0 ? (packedCount / totalCount * 100) : 0;

    container.innerHTML = `
        ${renderVacationBanner()}
        <button class="btn btn-secondary btn-sm" id="back-to-trips-btn">← Back to trips</button>
        <div class="trip-detail-header">
            <div class="trip-detail-title">${escapeHtml(trip.name)}</div>
            <div class="trip-detail-meta">${dest ? dest + ' · ' : ''}${dates}</div>
        </div>
        <div class="trip-actions">
            ${isActive
                ? '<button class="btn btn-secondary btn-sm" id="trip-deactivate-btn">Deactivate</button>'
                : '<button class="btn btn-primary btn-sm" id="trip-activate-btn">Activate</button>'
            }
            <button class="btn btn-secondary btn-sm" id="trip-edit-btn">Edit</button>
            <button class="btn btn-danger btn-sm" id="trip-delete-btn">Delete</button>
        </div>
        ${isActive ? '<div class="inline-note">Vacation mode filters Today, Closet and Outfits to packed items only.</div>' : ''}
        ${forecastHtml}
        <div class="packing-section">
            <div class="packing-section-title">Packing List</div>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <span class="trip-progress">${packedCount} of ${totalCount} packed</span>
                <div>
                    <button class="btn btn-sm btn-secondary" id="pack-all-btn">Pack all</button>
                    <button class="btn btn-sm btn-secondary" id="unpack-all-btn">Unpack all</button>
                </div>
            </div>
            <div class="packing-progress">
                <div class="packing-progress-bar" style="width: ${progressPct}%"></div>
            </div>
            <button class="btn btn-secondary btn-sm" id="auto-suggest-btn">Auto-suggest packing</button>
            ${packingListHtml}
            <button class="btn btn-secondary btn-block mt-md" id="add-items-btn">+ Add items</button>
        </div>
        <div class="packing-section">
            <div class="packing-section-title">Linked Outfits</div>
            <div>${linkedOutfitsHtml || '<div class="inline-note">No outfits linked</div>'}</div>
            <button class="btn btn-secondary btn-block mt-md" id="add-outfits-btn">+ Add outfits</button>
        </div>
    `;

    setupVacationBanner(container);

    document.getElementById('back-to-trips-btn').addEventListener('click', () => {
        state.tripDetail = null;
        renderTripsView(container);
    });

    document.getElementById('trip-edit-btn')?.addEventListener('click', () => openTripModal(trip));
    document.getElementById('trip-delete-btn')?.addEventListener('click', async () => {
        if (!confirm(`Delete trip "${trip.name}"?`)) return;
        try {
            await api(`/trips/${trip.id}`, { method: 'DELETE' });
            state.tripDetail = null;
            toast('Trip deleted');
            renderTripsView(container);
        } catch (err) {
            toast(err.message, 'error');
        }
    });

    document.getElementById('trip-activate-btn')?.addEventListener('click', async () => {
        try {
            await api(`/trips/${trip.id}/activate`, { method: 'POST' });
            state.activeTrip = null;
            state.tripDetail = await api(`/trips/${trip.id}`);
            toast('Vacation mode activated');
            renderTripDetailView(container);
        } catch (err) {
            toast(err.message, 'error');
        }
    });

    document.getElementById('trip-deactivate-btn')?.addEventListener('click', async () => {
        if (!confirm('Deactivate vacation mode?')) return;
        try {
            await api(`/trips/${trip.id}/deactivate`, { method: 'POST' });
            state.activeTrip = null;
            state.tripDetail = await api(`/trips/${trip.id}`);
            toast('Vacation mode deactivated');
            renderTripDetailView(container);
        } catch (err) {
            toast(err.message, 'error');
        }
    });

    document.getElementById('auto-suggest-btn')?.addEventListener('click', async () => {
        if (trip.items && trip.items.length > 0) {
            if (!confirm('This will add items to your current packing list. Continue?')) return;
        }
        try {
            const result = await api(`/trips/${trip.id}/suggest`, { method: 'POST' });
            const summary = result.suggestion_summary;
            const msg = `Added ${summary.outfits_added} outfits, ${summary.extras_added.length} extras`;
            toast(msg);
            state.tripDetail = result;
            renderTripDetailView(container);
        } catch (err) {
            toast(err.message, 'error');
        }
    });

    document.getElementById('pack-all-btn')?.addEventListener('click', async () => {
        try {
            state.tripDetail = await api(`/trips/${trip.id}/pack_all`, { method: 'POST', body: { packed: true } });
            renderTripDetailView(container);
        } catch (err) {
            toast(err.message, 'error');
        }
    });

    document.getElementById('unpack-all-btn')?.addEventListener('click', async () => {
        try {
            state.tripDetail = await api(`/trips/${trip.id}/pack_all`, { method: 'POST', body: { packed: false } });
            renderTripDetailView(container);
        } catch (err) {
            toast(err.message, 'error');
        }
    });

    container.querySelectorAll('.packing-checkbox').forEach(checkbox => {
        checkbox.addEventListener('click', async () => {
            const itemId = parseInt(checkbox.dataset.itemId);
            const packed = !checkbox.classList.contains('checked');
            try {
                await api(`/trips/${trip.id}/items/${itemId}`, { method: 'PATCH', body: { packed } });
                checkbox.classList.toggle('checked');
                state.tripDetail = await api(`/trips/${trip.id}`);
                renderTripDetailView(container);
            } catch (err) {
                toast(err.message, 'error');
            }
        });
    });

    container.querySelectorAll('.packing-item-remove').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const itemId = parseInt(btn.dataset.itemId);
            try {
                state.tripDetail = await api(`/trips/${trip.id}/items/${itemId}`, { method: 'DELETE' });
                renderTripDetailView(container);
            } catch (err) {
                toast(err.message, 'error');
            }
        });
    });

    container.querySelectorAll('.linked-outfit-chip .remove-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const chip = btn.closest('.linked-outfit-chip');
            const outfitId = parseInt(chip.dataset.outfitId);
            try {
                state.tripDetail = await api(`/trips/${trip.id}/outfits/${outfitId}`, { method: 'DELETE' });
                renderTripDetailView(container);
            } catch (err) {
                toast(err.message, 'error');
            }
        });
    });

    document.getElementById('add-items-btn')?.addEventListener('click', () => openTripItemPicker(trip));
    document.getElementById('add-outfits-btn')?.addEventListener('click', () => openTripOutfitPicker(trip));
}

async function openTripModal(trip = null) {
    const isNew = !trip;
    const title = isNew ? 'New Trip' : 'Edit Trip';

    let geocodeState = {
        query: trip?.destination || '',
        latitude: trip?.latitude || null,
        longitude: trip?.longitude || null,
        displayName: trip?.destination || ''
    };

    openModal(`
        <div class="modal-header">
            <span class="modal-title">${title}</span>
            <button class="modal-close" onclick="closeModal()">&times;</button>
        </div>
        <div class="modal-body">
            <div class="form-group">
                <label class="form-label">Trip Name</label>
                <input type="text" class="form-input" id="trip-name" value="${escapeHtml(trip?.name || '')}" required>
            </div>
            <div class="form-group">
                <label class="form-label">Destination</label>
                <div style="display: flex; gap: 8px;">
                    <input type="text" class="form-input" id="trip-destination" value="${escapeHtml(geocodeState.query)}" placeholder="City name" style="flex: 1;">
                    <button class="btn btn-secondary" id="geocode-lookup-btn">Look up</button>
                </div>
                <div id="geocode-results"></div>
                <div id="geocode-selected" class="inline-note" style="margin-top: 4px;"></div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label class="form-label">Start Date</label>
                    <input type="date" class="form-input" id="trip-start" value="${trip?.start_date || ''}" required>
                </div>
                <div class="form-group">
                    <label class="form-label">End Date</label>
                    <input type="date" class="form-input" id="trip-end" value="${trip?.end_date || ''}" required>
                </div>
            </div>
            <div class="form-group">
                <label class="form-label">Notes</label>
                <textarea class="form-textarea" id="trip-notes">${escapeHtml(trip?.notes || '')}</textarea>
            </div>
        </div>
        <div class="modal-footer">
            <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
            <button class="btn btn-primary" id="trip-save-btn">Save</button>
        </div>
    `);

    if (geocodeState.latitude && geocodeState.displayName) {
        document.getElementById('geocode-selected').textContent = `📍 ${geocodeState.displayName}`;
    }

    document.getElementById('geocode-lookup-btn').addEventListener('click', async () => {
        const query = document.getElementById('trip-destination').value.trim();
        if (!query) return;
        const resultsDiv = document.getElementById('geocode-results');
        resultsDiv.innerHTML = '<div class="inline-note">Looking up...</div>';
        try {
            const data = await api(`/trips/geocode?q=${encodeURIComponent(query)}`);
            if (data.results.length === 0) {
                resultsDiv.innerHTML = '<div class="inline-note">No results found</div>';
                return;
            }
            const resultsHtml = data.results.slice(0, 5).map(r => `
                <div class="geocode-result" data-lat="${r.latitude}" data-lon="${r.longitude}" data-name="${escapeHtml(r.name)}" data-country="${escapeHtml(r.country)}" data-admin1="${escapeHtml(r.admin1 || '')}">
                    <div class="geocode-result-name">${escapeHtml(r.name)}</div>
                    <div class="geocode-result-detail">${escapeHtml(r.admin1 ? r.admin1 + ', ' : '')}${escapeHtml(r.country)}</div>
                </div>
            `).join('');
            resultsDiv.innerHTML = `<div class="geocode-results">${resultsHtml}</div>`;
            resultsDiv.querySelectorAll('.geocode-result').forEach(result => {
                result.addEventListener('click', () => {
                    geocodeState.latitude = parseFloat(result.dataset.lat);
                    geocodeState.longitude = parseFloat(result.dataset.lon);
                    geocodeState.displayName = `${result.dataset.name}${result.dataset.admin1 ? ', ' + result.dataset.admin1 : ''}`;
                    document.getElementById('geocode-selected').textContent = `📍 ${geocodeState.displayName}`;
                    resultsDiv.innerHTML = '';
                });
            });
        } catch (err) {
            resultsDiv.innerHTML = `<div class="inline-note" style="color: var(--warning);">${escapeHtml(err.message)}</div>`;
        }
    });

    document.getElementById('trip-save-btn').addEventListener('click', async () => {
        const name = document.getElementById('trip-name').value.trim();
        const destination = document.getElementById('trip-destination').value.trim();
        const start_date = document.getElementById('trip-start').value;
        const end_date = document.getElementById('trip-end').value;
        const notes = document.getElementById('trip-notes').value.trim();

        if (!name || !start_date || !end_date) {
            toast('Name and dates required', 'error');
            return;
        }

        const body = { name, start_date, end_date, notes };
        if (destination) body.destination = destination;
        if (geocodeState.latitude !== null) {
            body.latitude = geocodeState.latitude;
            body.longitude = geocodeState.longitude;
        }

        try {
            if (isNew) {
                await api('/trips', { method: 'POST', body });
                toast('Trip created!');
            } else {
                await api(`/trips/${trip.id}`, { method: 'PATCH', body });
                toast('Trip updated!');
                state.tripDetail = null;
            }
            closeModal();
            renderTripsView(document.getElementById('main-content'));
        } catch (err) {
            toast(err.message, 'error');
        }
    });
}

async function openTripItemPicker(trip) {
    let allItems = [];
    try {
        allItems = await api('/items?lifecycle=active');
    } catch (err) {
        toast(err.message, 'error');
        return;
    }

    const tripItemIds = new Set((trip.items || []).map(i => i.id));
    const available = allItems.filter(i => !tripItemIds.has(i.id));

    const itemsHtml = available.map(item => `
        <div class="list-item selectable" data-item-id="${item.id}">
            <div class="list-item-photo">${getItemThumbHtml(item)}</div>
            <div class="list-item-content">
                <div class="list-item-title">#${item.number} ${escapeHtml(item.name)}</div>
                <div class="list-item-subtitle">${escapeHtml(item.category)}${item.color ? ' - ' + escapeHtml(item.color) : ''}</div>
            </div>
        </div>
    `).join('');

    openModal(`
        <div class="modal-header">
            <span class="modal-title">Add Items to Trip</span>
            <button class="modal-close" onclick="closeModal()">&times;</button>
        </div>
        <div class="modal-body">
            <div class="search-bar">
                <input type="text" placeholder="Search items..." id="trip-item-search">
            </div>
            <div id="trip-item-picker">${itemsHtml}</div>
        </div>
        <div class="modal-footer">
            <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
            <button class="btn btn-primary" id="trip-item-add-btn">Add Selected</button>
        </div>
    `);

    const selected = new Set();

    document.getElementById('trip-item-search').addEventListener('input', (e) => {
        const q = e.target.value.toLowerCase();
        document.querySelectorAll('#trip-item-picker .list-item').forEach(item => {
            const text = item.textContent.toLowerCase();
            item.style.display = text.includes(q) ? '' : 'none';
        });
    });

    document.querySelectorAll('#trip-item-picker .list-item').forEach(item => {
        item.addEventListener('click', () => {
            const itemId = parseInt(item.dataset.itemId);
            if (selected.has(itemId)) {
                selected.delete(itemId);
                item.classList.remove('selected');
            } else {
                selected.add(itemId);
                item.classList.add('selected');
            }
        });
    });

    document.getElementById('trip-item-add-btn').addEventListener('click', async () => {
        if (selected.size === 0) {
            toast('No items selected', 'error');
            return;
        }
        try {
            state.tripDetail = await api(`/trips/${trip.id}/items`, { method: 'POST', body: { item_ids: Array.from(selected) } });
            closeModal();
            toast(`${selected.size} items added`);
            renderTripDetailView(document.getElementById('main-content'));
        } catch (err) {
            toast(err.message, 'error');
        }
    });
}

async function openTripOutfitPicker(trip) {
    let allOutfits = [];
    try {
        allOutfits = await api('/outfits');
    } catch (err) {
        toast(err.message, 'error');
        return;
    }

    const linkedIds = new Set((trip.outfits || []).map(o => o.id));
    const available = allOutfits.filter(o => o.status === 'active' && !linkedIds.has(o.id));

    const outfitsHtml = available.map(outfit => {
        const thumbsHtml = (outfit.items || []).slice(0, 3).map(item =>
            `<div class="item-thumb">${getItemThumbHtml(item)}</div>`
        ).join('');
        return `
            <div class="list-item selectable" data-outfit-id="${outfit.id}">
                <div class="list-item-content">
                    <div class="list-item-title">${escapeHtml(outfit.name)}</div>
                    <div class="outfit-thumbnails" style="margin-top: 4px;">${thumbsHtml}</div>
                </div>
            </div>
        `;
    }).join('');

    openModal(`
        <div class="modal-header">
            <span class="modal-title">Add Outfits to Trip</span>
            <button class="modal-close" onclick="closeModal()">&times;</button>
        </div>
        <div class="modal-body">
            <div id="trip-outfit-picker">${outfitsHtml}</div>
        </div>
        <div class="modal-footer">
            <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
            <button class="btn btn-primary" id="trip-outfit-add-btn">Add Selected</button>
        </div>
    `);

    const selected = new Set();

    document.querySelectorAll('#trip-outfit-picker .list-item').forEach(item => {
        item.addEventListener('click', () => {
            const outfitId = parseInt(item.dataset.outfitId);
            if (selected.has(outfitId)) {
                selected.delete(outfitId);
                item.classList.remove('selected');
            } else {
                selected.add(outfitId);
                item.classList.add('selected');
            }
        });
    });

    document.getElementById('trip-outfit-add-btn').addEventListener('click', async () => {
        if (selected.size === 0) {
            toast('No outfits selected', 'error');
            return;
        }
        try {
            state.tripDetail = await api(`/trips/${trip.id}/outfits`, { method: 'POST', body: { outfit_ids: Array.from(selected) } });
            closeModal();
            toast(`${selected.size} outfits added`);
            renderTripDetailView(document.getElementById('main-content'));
        } catch (err) {
            toast(err.message, 'error');
        }
    });
}

// ========================================
// SETTINGS VIEW
// ========================================

async function renderSettingsView(container) {
    container.innerHTML = '<div class="flex-center"><div class="spinner"></div></div>';

    try {
        await loadSettings();
    } catch (err) {
        container.innerHTML = `<div class="empty-state"><div class="empty-state-text">Error: ${escapeHtml(err.message)}</div></div>`;
        return;
    }

    const s = state.settings;

    const categories = s.categories || [];
    const categoryRows = categories.map((c, idx) => {
        const cat = typeof c === 'string' ? { name: c, role: 'optional', weather: 'any', max_per_outfit: 1, pick_prob: 0.2, group: '', rest_days: 0 } : c;
        return `
            <tr data-index="${idx}">
                <td><input type="text" class="cat-name" value="${escapeHtml(cat.name)}" required></td>
                <td>
                    <select class="cat-role">
                        <option value="required" ${cat.role === 'required' ? 'selected' : ''}>required</option>
                        <option value="optional" ${cat.role === 'optional' ? 'selected' : ''}>optional</option>
                    </select>
                </td>
                <td>
                    <select class="cat-weather">
                        <option value="any" ${cat.weather === 'any' ? 'selected' : ''}>any</option>
                        <option value="cold" ${cat.weather === 'cold' ? 'selected' : ''}>cold</option>
                        <option value="sun" ${cat.weather === 'sun' ? 'selected' : ''}>sun</option>
                    </select>
                </td>
                <td><input type="number" class="cat-max" value="${cat.max_per_outfit}" min="1" max="3" style="width: 50px;"></td>
                <td><input type="number" class="cat-prob" value="${Math.round(cat.pick_prob * 100)}" min="0" max="100" step="5" style="width: 55px;">%</td>
                <td><input type="number" class="cat-rest" value="${cat.rest_days || 0}" min="0" style="width: 50px;"></td>
                <td>
                    <select class="cat-group">
                        <option value="" ${cat.group === '' ? 'selected' : ''}>-</option>
                        <option value="accessories" ${cat.group === 'accessories' ? 'selected' : ''}>accessories</option>
                    </select>
                </td>
                <td><button class="category-delete-btn" data-index="${idx}">&times;</button></td>
            </tr>
        `;
    }).join('');

    const seasonChipsHtml = (s.season_tags || []).map(t =>
        `<span class="chip" data-value="${escapeHtml(t)}">${escapeHtml(t)}<span class="remove-btn">&times;</span></span>`
    ).join('');

    const vibeChipsHtml = (s.vibe_tags || []).map(t =>
        `<span class="chip" data-value="${escapeHtml(t)}">${escapeHtml(t)}<span class="remove-btn">&times;</span></span>`
    ).join('');

    const categoryNames = categories.map(c => typeof c === 'string' ? c : c.name);
    const thresholdsHtml = categoryNames.map(cat => `
        <div class="threshold-row">
            <span class="threshold-label">${escapeHtml(cat)}</span>
            <input type="number" class="form-input threshold-input" data-category="${escapeHtml(cat)}"
                   value="${s.dirty_thresholds?.[cat] || 0}" min="0">
        </div>
    `).join('');

    // Weather rules
    const weatherRules = s.weather_rules || {};
    const colorRules = s.color_rules || {};
    const sensitiveMaterials = weatherRules.sensitive_materials || [];
    const sensitiveMaterialsChipsHtml = sensitiveMaterials.map(m =>
        `<span class="chip" data-value="${escapeHtml(m)}">${escapeHtml(m)}<span class="remove-btn">&times;</span></span>`
    ).join('');

    container.innerHTML = `
        <div class="settings-section">
            <div class="settings-section-title">Suggestions</div>
            <div class="form-group">
                <label class="form-label">No Repeat Days</label>
                <input type="number" class="form-input" id="no-repeat-days" value="${s.no_repeat_days || 0}" min="0">
                <p class="settings-note">Hide outfits worn in the last N days from suggestions (0 = off)</p>
            </div>
            <button class="btn btn-primary" id="save-suggestions-btn">Save</button>
        </div>

        <div class="settings-section">
            <div class="settings-section-title">Weather Rules</div>
            <div class="form-row">
                <div class="form-group">
                    <label class="form-label">Rain Precip Threshold (%)</label>
                    <input type="number" class="form-input" id="rain-threshold" value="${weatherRules.rain_precip_threshold || ''}" min="0" max="100">
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label class="form-label">Cold Below (F)</label>
                    <input type="number" class="form-input" id="cold-below" value="${weatherRules.outerwear_below_f || ''}">
                </div>
                <div class="form-group">
                    <label class="form-label">Warm Above (F)</label>
                    <input type="number" class="form-input" id="warm-above" value="${weatherRules.no_outerwear_above_f || ''}">
                </div>
            </div>
            <div class="form-group">
                <label class="form-label">Sensitive Materials</label>
                <div class="tag-editor" id="sensitive-materials-editor">${sensitiveMaterialsChipsHtml}</div>
                <div class="tag-input-row">
                    <input type="text" class="form-input" id="new-sensitive-material" placeholder="e.g. suede, silk...">
                    <button class="btn btn-secondary" id="add-sensitive-material-btn">Add</button>
                </div>
                <p class="settings-note">Materials to avoid when rain is likely</p>
            </div>
            <button class="btn btn-primary" id="save-weather-rules-btn">Save Weather Rules</button>
        </div>

        <div class="settings-section">
            <div class="settings-section-title">Color Rules</div>
            <div class="form-group">
                <label class="form-label" style="display: flex; align-items: center; gap: 8px;">
                    <input type="checkbox" id="color-rules-enabled" ${colorRules.enabled ? 'checked' : ''}>
                    Enable color harmony in outfit generation
                </label>
            </div>
            <div class="form-group">
                <label class="form-label">Neutral Colors</label>
                <input type="text" class="form-input" id="color-neutrals" value="${escapeHtml((colorRules.neutrals || []).join(', '))}">
                <p class="settings-note">Comma-separated. Neutrals pair with anything (matches item color text, e.g. "navy blue" matches "navy").</p>
            </div>
            <div class="form-group">
                <label class="form-label">Max Statement Colors</label>
                <input type="number" class="form-input" id="color-max-statement" value="${colorRules.max_statement_colors ?? 1}" min="0" max="5">
                <p class="settings-note">Max distinct non-neutral colors per generated outfit.</p>
            </div>
            <div class="form-group">
                <label class="form-label">Never Pair</label>
                <textarea class="form-input" id="color-never-pair" rows="3" placeholder="e.g.&#10;brown, black&#10;red, pink">${escapeHtml((colorRules.never_pair || []).map(p => (p || []).join(', ')).join('\n'))}</textarea>
                <p class="settings-note">One pair per line: "colorA, colorB". Generation never combines them.</p>
            </div>
            <button class="btn btn-primary" id="save-color-rules-btn">Save Color Rules</button>
        </div>

        <div class="settings-section">
            <div class="settings-section-title">Backup</div>
            <div class="backup-buttons">
                <a href="/api/backup/zip" class="btn btn-secondary" download>Download Full Backup (.zip)</a>
                <a href="/api/backup/json" class="btn btn-secondary" download>Export JSON</a>
            </div>
        </div>

        <div class="settings-section">
            <div class="settings-section-title">Import</div>
            <div class="form-group">
                <a href="/api/import/csv/template" class="btn btn-outline btn-block" download>Download CSV Template</a>
            </div>
            <div class="form-group">
                <label class="form-label">Import from CSV</label>
                <div class="file-input-wrapper">
                    <input type="file" class="file-input" accept=".csv" id="csv-import-input">
                    <div class="file-input-btn">
                        <span>Choose CSV file</span>
                    </div>
                </div>
            </div>
            <button class="btn btn-secondary btn-block mb-md" id="csv-check-btn" disabled>Check File</button>
            <div id="csv-import-results" class="hidden"></div>
            <button class="btn btn-primary btn-block" id="csv-import-btn" disabled>Import Items</button>
        </div>

        <div class="settings-section">
            <div class="settings-section-title">Location</div>
            <div class="form-group">
                <label class="form-label">Location Name</label>
                <input type="text" class="form-input" id="location-name" value="${escapeHtml(s.location_name || '')}">
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label class="form-label">Latitude</label>
                    <input type="number" step="any" class="form-input" id="latitude" value="${s.latitude || ''}">
                </div>
                <div class="form-group">
                    <label class="form-label">Longitude</label>
                    <input type="number" step="any" class="form-input" id="longitude" value="${s.longitude || ''}">
                </div>
            </div>
            <button class="btn btn-primary" id="save-location-btn">Save Location</button>
            <p class="settings-note">Used for weather. Find coords on maps.</p>
        </div>

        <div class="settings-section">
            <div class="settings-section-title">Categories</div>
            <p class="inline-note">Required categories appear in every generated outfit. Pick chance controls how often optional pieces are added. At most 2 accessory-group items per outfit. Rest = days an item needs between wears before it's suggested again (0 = off).</p>
            <table class="category-editor-table" id="categories-table">
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Role</th>
                        <th>Weather</th>
                        <th>Max</th>
                        <th>Pick%</th>
                        <th>Rest</th>
                        <th>Group</th>
                        <th></th>
                    </tr>
                </thead>
                <tbody id="categories-tbody">
                    ${categoryRows}
                </tbody>
            </table>
            <button class="btn btn-secondary" id="add-category-row-btn">+ Add Category</button>
            <button class="btn btn-primary" id="save-categories-btn" style="margin-left: 8px;">Save Categories</button>
        </div>

        <div class="settings-section">
            <div class="settings-section-title">Season Tags</div>
            <div class="tag-editor" id="seasons-editor">${seasonChipsHtml}</div>
            <div class="tag-input-row">
                <input type="text" class="form-input" id="new-season" placeholder="New season tag...">
                <button class="btn btn-secondary" id="add-season-btn">Add</button>
            </div>
        </div>

        <div class="settings-section">
            <div class="settings-section-title">Vibe Tags</div>
            <div class="tag-editor" id="vibes-editor">${vibeChipsHtml}</div>
            <div class="tag-input-row">
                <input type="text" class="form-input" id="new-vibe" placeholder="New vibe tag...">
                <button class="btn btn-secondary" id="add-vibe-btn">Add</button>
            </div>
        </div>

        <div class="settings-section">
            <div class="settings-section-title">Dirty Thresholds</div>
            <p class="settings-note" style="margin-bottom: 8px;">Wears before suggesting item is dirty (0 = never)</p>
            ${thresholdsHtml}
            <button class="btn btn-primary mt-md" id="save-thresholds-btn">Save Thresholds</button>
        </div>

        <div class="settings-section">
            <div class="settings-section-title">Season Temperature Bands</div>
            <div class="form-row">
                <div class="form-group">
                    <label class="form-label">Summer Min (F)</label>
                    <input type="number" class="form-input" id="summer-min" value="${s.season_temp_bands?.summer_min_f || ''}">
                </div>
                <div class="form-group">
                    <label class="form-label">Winter Max (F)</label>
                    <input type="number" class="form-input" id="winter-max" value="${s.season_temp_bands?.winter_max_f || ''}">
                </div>
            </div>
            <button class="btn btn-primary" id="save-temp-btn">Save Temp Bands</button>
        </div>
    `;

    // Save suggestions settings (no_repeat_days)
    document.getElementById('save-suggestions-btn').addEventListener('click', async () => {
        try {
            await api('/settings', {
                method: 'PUT',
                body: {
                    no_repeat_days: parseInt(document.getElementById('no-repeat-days').value) || 0
                }
            });
            toast('Suggestions settings saved!');
            state.settings = null;
        } catch (err) {
            toast(err.message, 'error');
        }
    });

    // Save weather rules
    document.getElementById('save-weather-rules-btn').addEventListener('click', async () => {
        try {
            const currentMaterials = Array.from(document.querySelectorAll('#sensitive-materials-editor .chip')).map(c => c.dataset.value);
            await api('/settings', {
                method: 'PUT',
                body: {
                    weather_rules: {
                        rain_precip_threshold: parseInt(document.getElementById('rain-threshold').value) || null,
                        outerwear_below_f: parseInt(document.getElementById('cold-below').value) || null,
                        no_outerwear_above_f: parseInt(document.getElementById('warm-above').value) || null,
                        sensitive_materials: currentMaterials
                    }
                }
            });
            toast('Weather rules saved!');
            state.settings = null;
        } catch (err) {
            toast(err.message, 'error');
        }
    });

    // Save color rules
    document.getElementById('save-color-rules-btn').addEventListener('click', async () => {
        try {
            const neutrals = document.getElementById('color-neutrals').value
                .split(',').map(t => t.trim().toLowerCase()).filter(Boolean);
            const never_pair = document.getElementById('color-never-pair').value
                .split('\n')
                .map(line => line.split(',').map(t => t.trim().toLowerCase()).filter(Boolean))
                .filter(pair => pair.length >= 2)
                .map(pair => [pair[0], pair[1]]);
            await api('/settings', {
                method: 'PUT',
                body: {
                    color_rules: {
                        enabled: document.getElementById('color-rules-enabled').checked,
                        neutrals,
                        max_statement_colors: parseInt(document.getElementById('color-max-statement').value) || 0,
                        never_pair
                    }
                }
            });
            toast('Color rules saved!');
            state.settings = null;
        } catch (err) {
            toast(err.message, 'error');
        }
    });

    // Sensitive materials tag editor
    setupSensitiveMaterialsEditor();

    // CSV Import
    setupCsvImport();

    // Save location
    document.getElementById('save-location-btn').addEventListener('click', async () => {
        try {
            await api('/settings', {
                method: 'PUT',
                body: {
                    location_name: document.getElementById('location-name').value,
                    latitude: parseFloat(document.getElementById('latitude').value) || null,
                    longitude: parseFloat(document.getElementById('longitude').value) || null
                }
            });
            toast('Location saved!');
            state.settings = null; // Force reload
        } catch (err) {
            toast(err.message, 'error');
        }
    });

    // Tag editors
    setupCategoryEditor();
    setupTagEditor('seasons-editor', 'new-season', 'add-season-btn', 'season_tags');
    setupTagEditor('vibes-editor', 'new-vibe', 'add-vibe-btn', 'vibe_tags');

    // Save thresholds
    document.getElementById('save-thresholds-btn').addEventListener('click', async () => {
        const thresholds = {};
        document.querySelectorAll('.threshold-input').forEach(input => {
            thresholds[input.dataset.category] = parseInt(input.value) || 0;
        });
        try {
            await api('/settings', { method: 'PUT', body: { dirty_thresholds: thresholds } });
            toast('Thresholds saved!');
            state.settings = null;
        } catch (err) {
            toast(err.message, 'error');
        }
    });

    // Save temp bands
    document.getElementById('save-temp-btn').addEventListener('click', async () => {
        try {
            await api('/settings', {
                method: 'PUT',
                body: {
                    season_temp_bands: {
                        summer_min_f: parseInt(document.getElementById('summer-min').value) || 0,
                        winter_max_f: parseInt(document.getElementById('winter-max').value) || 0
                    }
                }
            });
            toast('Temperature bands saved!');
            state.settings = null;
        } catch (err) {
            toast(err.message, 'error');
        }
    });
}

function setupCategoryEditor() {
    const tbody = document.getElementById('categories-tbody');
    const addBtn = document.getElementById('add-category-row-btn');
    const saveBtn = document.getElementById('save-categories-btn');

    // Add new category row
    addBtn.addEventListener('click', () => {
        const newRow = document.createElement('tr');
        newRow.innerHTML = `
            <td><input type="text" class="cat-name" value="" required></td>
            <td>
                <select class="cat-role">
                    <option value="required">required</option>
                    <option value="optional" selected>optional</option>
                </select>
            </td>
            <td>
                <select class="cat-weather">
                    <option value="any" selected>any</option>
                    <option value="cold">cold</option>
                    <option value="sun">sun</option>
                </select>
            </td>
            <td><input type="number" class="cat-max" value="1" min="1" max="3" style="width: 50px;"></td>
            <td><input type="number" class="cat-prob" value="20" min="0" max="100" step="5" style="width: 55px;">%</td>
            <td><input type="number" class="cat-rest" value="0" min="0" style="width: 50px;"></td>
            <td>
                <select class="cat-group">
                    <option value="" selected>-</option>
                    <option value="accessories">accessories</option>
                </select>
            </td>
            <td><button class="category-delete-btn">&times;</button></td>
        `;
        tbody.appendChild(newRow);
    });

    // Delete category
    tbody.addEventListener('click', (e) => {
        const deleteBtn = e.target.closest('.category-delete-btn');
        if (!deleteBtn) return;
        const row = deleteBtn.closest('tr');
        const nameInput = row.querySelector('.cat-name');
        if (!confirm(`Delete category "${nameInput.value}"? This does not delete items, only the category definition.`)) return;
        row.remove();
    });

    // Save categories
    saveBtn.addEventListener('click', async () => {
        const rows = tbody.querySelectorAll('tr');
        const categories = Array.from(rows).map(row => {
            const name = row.querySelector('.cat-name').value.trim();
            const role = row.querySelector('.cat-role').value;
            const weather = row.querySelector('.cat-weather').value;
            const max_per_outfit = parseInt(row.querySelector('.cat-max').value);
            const pick_prob = parseFloat(row.querySelector('.cat-prob').value) / 100;
            const group = row.querySelector('.cat-group').value;
            const rest_days = parseInt(row.querySelector('.cat-rest').value) || 0;
            return { name, role, weather, max_per_outfit, pick_prob, group, rest_days };
        }).filter(c => c.name);

        if (categories.length === 0) {
            toast('At least one category required', 'error');
            return;
        }

        try {
            await api('/settings', { method: 'PUT', body: { categories } });
            toast('Categories saved!');
            state.settings = null;
            renderSettingsView(document.getElementById('main-content'));
        } catch (err) {
            toast(err.message, 'error');
        }
    });
}

function setupTagEditor(editorId, inputId, btnId, settingsKey) {
    const editor = document.getElementById(editorId);
    const input = document.getElementById(inputId);
    const btn = document.getElementById(btnId);

    // Remove tags
    editor.addEventListener('click', async (e) => {
        const removeBtn = e.target.closest('.remove-btn');
        if (!removeBtn) return;

        const chip = removeBtn.closest('.chip');
        const value = chip.dataset.value;

        const currentTags = state.settings[settingsKey] || [];
        const newTags = currentTags.filter(t => t !== value);

        try {
            await api('/settings', { method: 'PUT', body: { [settingsKey]: newTags } });
            state.settings = null;
            toast('Removed!');
            renderSettingsView(document.getElementById('main-content'));
        } catch (err) {
            toast(err.message, 'error');
        }
    });

    // Add tag
    btn.addEventListener('click', async () => {
        const value = input.value.trim();
        if (!value) return;

        const currentTags = state.settings[settingsKey] || [];
        if (currentTags.includes(value)) {
            toast('Already exists', 'error');
            return;
        }

        try {
            await api('/settings', { method: 'PUT', body: { [settingsKey]: [...currentTags, value] } });
            state.settings = null;
            toast('Added!');
            renderSettingsView(document.getElementById('main-content'));
        } catch (err) {
            toast(err.message, 'error');
        }
    });

    // Enter key to add
    input.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            btn.click();
        }
    });
}

function setupSensitiveMaterialsEditor() {
    const editor = document.getElementById('sensitive-materials-editor');
    const input = document.getElementById('new-sensitive-material');
    const btn = document.getElementById('add-sensitive-material-btn');

    if (!editor || !input || !btn) return;

    // Remove material
    editor.addEventListener('click', (e) => {
        const removeBtn = e.target.closest('.remove-btn');
        if (!removeBtn) return;
        const chip = removeBtn.closest('.chip');
        chip.remove();
    });

    // Add material
    btn.addEventListener('click', () => {
        const value = input.value.trim();
        if (!value) return;

        // Check if already exists
        const existing = Array.from(editor.querySelectorAll('.chip')).map(c => c.dataset.value);
        if (existing.includes(value)) {
            toast('Already exists', 'error');
            return;
        }

        const chip = document.createElement('span');
        chip.className = 'chip';
        chip.dataset.value = value;
        chip.innerHTML = `${escapeHtml(value)}<span class="remove-btn">&times;</span>`;
        editor.appendChild(chip);
        input.value = '';
    });

    // Enter key
    input.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            btn.click();
        }
    });
}

function setupCsvImport() {
    const fileInput = document.getElementById('csv-import-input');
    const checkBtn = document.getElementById('csv-check-btn');
    const importBtn = document.getElementById('csv-import-btn');
    const resultsDiv = document.getElementById('csv-import-results');

    if (!fileInput || !checkBtn || !importBtn || !resultsDiv) return;

    let lastValidCount = 0;

    fileInput.addEventListener('change', () => {
        checkBtn.disabled = !fileInput.files[0];
        importBtn.disabled = true;
        resultsDiv.classList.add('hidden');
        lastValidCount = 0;
    });

    checkBtn.addEventListener('click', async () => {
        const file = fileInput.files[0];
        if (!file) return;

        const formData = new FormData();
        formData.append('file', file);

        resultsDiv.classList.remove('hidden');
        resultsDiv.innerHTML = '<div class="spinner" style="margin: 8px auto;"></div>';

        try {
            const result = await api('/import/csv?dry_run=true', { method: 'POST', body: formData });
            lastValidCount = result.valid || 0;

            let html = '';
            if (lastValidCount > 0) {
                html += `<div class="csv-valid-count" style="color: var(--success); margin-bottom: 8px;">${lastValidCount} valid items found</div>`;
            }
            if (result.errors && result.errors.length > 0) {
                html += '<div class="csv-errors" style="color: var(--danger);">';
                html += '<div style="font-weight: 600; margin-bottom: 4px;">Errors:</div>';
                result.errors.forEach(err => {
                    html += `<div>Row ${err.row}: ${escapeHtml(err.reason)}</div>`;
                });
                html += '</div>';
            }

            resultsDiv.innerHTML = html || '<div class="text-muted">No items found</div>';
            importBtn.disabled = lastValidCount === 0;
            importBtn.textContent = `Import ${lastValidCount} Items`;
        } catch (err) {
            resultsDiv.innerHTML = `<span style="color: var(--danger);">${escapeHtml(err.message)}</span>`;
            importBtn.disabled = true;
        }
    });

    importBtn.addEventListener('click', async () => {
        const file = fileInput.files[0];
        if (!file) return;

        const formData = new FormData();
        formData.append('file', file);

        importBtn.disabled = true;
        importBtn.innerHTML = '<div class="spinner"></div>';

        try {
            const result = await api('/import/csv?dry_run=false', { method: 'POST', body: formData });
            toast(`Imported ${result.created} items!`);
            // Reset form
            fileInput.value = '';
            checkBtn.disabled = true;
            importBtn.disabled = true;
            importBtn.textContent = 'Import Items';
            resultsDiv.classList.add('hidden');
            // Refresh closet
            state.items = await api('/items');
        } catch (err) {
            toast(err.message, 'error');
            importBtn.disabled = false;
            importBtn.textContent = `Import ${lastValidCount} Items`;
        }
    });
}

// ========================================
// Data Loading Helpers
// ========================================

async function loadSettings() {
    if (!state.settings) {
        state.settings = await api('/settings');
    }
    return state.settings;
}

// Active-trip cache: avoids re-fetching /trips/active on every view render.
// Invalidated automatically by api() on any non-GET /trips request.
let _activeTripCache = null; // { value, ts }
const TRIP_CACHE_MS = 60000;

function invalidateTripCache() {
    _activeTripCache = null;
}

async function loadActiveTrip(force = false) {
    if (!force && _activeTripCache && (Date.now() - _activeTripCache.ts) < TRIP_CACHE_MS) {
        state.activeTrip = _activeTripCache.value;
        return state.activeTrip;
    }
    const data = await api('/trips/active');
    state.activeTrip = data.active;
    _activeTripCache = { value: state.activeTrip, ts: Date.now() };
    return state.activeTrip;
}

// ========================================
// CARE / MAINTENANCE VIEW
// ========================================

async function renderCareView(container) {
    container.innerHTML = '<div class="flex-center"><div class="spinner"></div></div>';

    try {
        const [, dueData, guides, suppliesData, seasonalData] = await Promise.all([
            loadSettings(),
            api('/care/due'),
            api('/care/guides'),
            api('/care/supplies'),
            api('/care/seasonal')
        ]);

        const dueCount = dueData.count || 0;
        const dueItems = dueData.items || [];

        let dueHtml = '';
        if (dueCount === 0) {
            dueHtml = '<div class="empty-state"><div class="empty-state-text">All caught up! No items need care right now.</div></div>';
        } else {
            dueHtml = dueItems.map(entry => {
                const item = entry.item;
                const tasks = entry.due_tasks || [];
                const taskChips = tasks.map(t => {
                    let reason = '';
                    if (t.wears_since !== null && t.wears_since !== undefined) {
                        reason = `${t.wears_since} wears since`;
                    } else if (t.days_since !== null && t.days_since !== undefined) {
                        reason = `${t.days_since} days since`;
                    }
                    return `
                        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
                            <span class="chip small" style="background: var(--danger); color: white;">${escapeHtml(t.label)}</span>
                            <span style="font-size: 12px; color: var(--text-secondary);">${reason}</span>
                            <button class="btn btn-sm" style="margin-left: auto;" data-item-id="${item.id}" data-task="${escapeHtml(t.task)}">Done</button>
                        </div>
                    `;
                }).join('');

                return `
                    <div class="list-item" style="flex-direction: column; align-items: flex-start; cursor: default;">
                        <div style="display: flex; gap: var(--space-md); width: 100%; align-items: center;">
                            <div class="list-item-photo" style="cursor: pointer;" data-item-id="${item.id}">
                                ${item.photo ? `<img src="${escapeHtml(item.photo)}" alt="${escapeHtml(item.name)}" loading="lazy">` : `<span class="placeholder">#</span>`}
                            </div>
                            <div class="list-item-content">
                                <div class="list-item-title">${escapeHtml(item.name)}</div>
                                <div class="list-item-subtitle">${escapeHtml(item.category)}${item.materials && item.materials.length > 0 ? ' • ' + item.materials.join(', ') : ''}</div>
                            </div>
                        </div>
                        <div style="margin-top: var(--space-sm); width: 100%;">
                            ${taskChips}
                        </div>
                    </div>
                `;
            }).join('');
        }

        const guidesHtml = guides.length === 0
            ? '<div class="empty-state"><div class="empty-state-text">No care guides available</div></div>'
            : `<div class="item-grid">${guides.map(g => {
                const materialTags = (g.materials || []).map(m => `<span class="chip small">${escapeHtml(m)}</span>`).join('');
                const categoryTags = (g.categories || []).map(c => `<span class="chip small">${escapeHtml(c)}</span>`).join('');
                return `
                    <div class="card" style="cursor: pointer;" data-guide-id="${escapeHtml(g.id)}">
                        <div class="card-title" style="font-size: 16px; margin-bottom: 8px;">${escapeHtml(g.title)}</div>
                        <p style="font-size: 13px; color: var(--text-secondary); margin-bottom: 8px;">${escapeHtml(g.summary)}</p>
                        <div class="chip-row">
                            ${materialTags}
                            ${categoryTags}
                        </div>
                    </div>
                `;
            }).join('')}</div>`;

        // Seasonal storage assistant banner (spring: store, fall: reactivate)
        let seasonalHtml = '';
        if (seasonalData.mode && (seasonalData.items || []).length > 0) {
            const isStore = seasonalData.mode === 'store';
            const title = isStore
                ? `Seasonal storage: ${seasonalData.items.length} cold-weather items still active`
                : `Season change: ${seasonalData.items.length} stored items to bring back out`;
            const itemNames = seasonalData.items.map(i => escapeHtml(i.name)).join(', ');
            const checklist = (seasonalData.checklist || []).map(s =>
                `<li style="margin-bottom: var(--space-xs);">${escapeHtml(s)}</li>`
            ).join('');
            seasonalHtml = `
                <div class="card" style="margin-bottom: var(--space-md); border-left: 3px solid var(--warning);">
                    <div class="card-header" id="seasonal-toggle" style="cursor: pointer;">
                        <span class="card-title">${title}</span>
                        <span class="link-text" style="font-size: 13px;">Details</span>
                    </div>
                    <div id="seasonal-body" style="display: none;">
                        <p style="font-size: 13px; color: var(--text-secondary); margin-bottom: var(--space-sm);">${itemNames}</p>
                        <ul style="margin: 0; padding-left: var(--space-md); font-size: 13px; color: var(--text-secondary);">
                            ${checklist}
                        </ul>
                    </div>
                </div>
            `;
        }

        // Care kit (supplies checklist)
        const supplies = suppliesData.supplies || [];
        const neededCount = supplies.filter(s => !s.owned).length;
        const suppliesRows = supplies.length === 0
            ? '<p class="text-muted" style="font-size: 13px;">Add items with materials to build your care kit.</p>'
            : supplies.map(s => `
                <label style="display: flex; align-items: center; gap: 8px; padding: var(--space-xs) 0; border-bottom: 1px solid var(--border); font-size: 14px; cursor: pointer;">
                    <input type="checkbox" class="supply-check" data-supply="${escapeHtml(s.name.toLowerCase())}" ${s.owned ? 'checked' : ''}>
                    <span style="${s.owned ? 'color: var(--text-secondary);' : ''}">${escapeHtml(s.name)}</span>
                    <span style="margin-left: auto; font-size: 12px; color: var(--text-secondary);">${s.item_count} item${s.item_count === 1 ? '' : 's'}</span>
                </label>
            `).join('');
        const careKitHtml = `
            <div class="card" style="margin-top: var(--space-lg);">
                <div class="card-header" id="care-kit-toggle" style="cursor: pointer;">
                    <span class="card-title">Care Kit</span>
                    ${neededCount > 0 ? `<span class="badge">${neededCount} needed</span>` : '<span style="font-size: 13px; color: var(--text-secondary);">All stocked</span>'}
                </div>
                <div id="care-kit-body" style="display: none;">
                    <p style="font-size: 12px; color: var(--text-secondary); margin-bottom: var(--space-sm);">Supplies recommended by the care guides that match your wardrobe. Check off what you own.</p>
                    ${suppliesRows}
                </div>
            </div>
        `;

        container.innerHTML = `
            <h2 style="font-size: 24px; font-weight: 600; margin-bottom: var(--space-md);">Maintenance & Care</h2>
            ${seasonalHtml}
            <div class="card">
                <div class="card-header">
                    <span class="card-title">Needs Attention</span>
                    ${dueCount > 0 ? `<span class="badge" style="background: var(--danger); color: white;">${dueCount}</span>` : ''}
                </div>
                ${dueHtml}
            </div>
            ${careKitHtml}
            <div style="margin-top: var(--space-lg);">
                <h3 style="font-size: 18px; font-weight: 600; margin-bottom: var(--space-md);">Care Guides</h3>
                ${guidesHtml}
            </div>
        `;

        // Seasonal banner expand/collapse
        document.getElementById('seasonal-toggle')?.addEventListener('click', () => {
            const body = document.getElementById('seasonal-body');
            body.style.display = body.style.display === 'none' ? 'block' : 'none';
        });

        // Care kit expand/collapse
        document.getElementById('care-kit-toggle')?.addEventListener('click', () => {
            const body = document.getElementById('care-kit-body');
            body.style.display = body.style.display === 'none' ? 'block' : 'none';
        });

        // Care kit owned toggles -> persist to settings
        container.querySelectorAll('.supply-check').forEach(cb => {
            cb.addEventListener('change', async () => {
                const owned = Array.from(container.querySelectorAll('.supply-check'))
                    .filter(c => c.checked)
                    .map(c => c.dataset.supply);
                try {
                    await api('/settings', { method: 'PUT', body: { care_supplies_owned: owned } });
                    state.settings = null;
                } catch (err) {
                    toast(err.message, 'error');
                    cb.checked = !cb.checked;
                }
            });
        });

        // Wire up "Done" buttons
        container.querySelectorAll('[data-task]').forEach(btn => {
            btn.addEventListener('click', async () => {
                const itemId = parseInt(btn.dataset.itemId);
                const task = btn.dataset.task;
                try {
                    await api(`/items/${itemId}/care/log`, {
                        method: 'POST',
                        body: { task, date: localToday() }
                    });
                    toast('Care task logged!');
                    renderCareView(container);
                } catch (err) {
                    toast(err.message, 'error');
                }
            });
        });

        // Wire up item photo clicks
        container.querySelectorAll('.list-item-photo[data-item-id]').forEach(photo => {
            photo.addEventListener('click', async () => {
                const itemId = parseInt(photo.dataset.itemId);
                openItemCareModal(itemId);
            });
        });

        // Wire up guide cards
        container.querySelectorAll('[data-guide-id]').forEach(card => {
            card.addEventListener('click', async () => {
                const guideId = card.dataset.guideId;
                openGuideModal(guideId);
            });
        });

    } catch (err) {
        container.innerHTML = `<div class="empty-state"><div class="empty-state-text">Error: ${escapeHtml(err.message)}</div></div>`;
    }
}

async function openGuideModal(guideId) {
    try {
        const guide = await api(`/care/guides/${guideId}`);

        const sectionsHtml = (guide.sections || []).map(s => `
            <div style="margin-bottom: var(--space-md);">
                <h4 style="font-size: 14px; font-weight: 600; margin-bottom: var(--space-xs);">${escapeHtml(s.heading)}</h4>
                <ul style="margin: 0; padding-left: var(--space-md); font-size: 13px; color: var(--text-secondary);">
                    ${s.steps.map(step => `<li style="margin-bottom: var(--space-xs);">${escapeHtml(step)}</li>`).join('')}
                </ul>
            </div>
        `).join('');

        const suppliesHtml = guide.supplies && guide.supplies.length > 0
            ? `<div style="margin-bottom: var(--space-md);">
                <h4 style="font-size: 14px; font-weight: 600; margin-bottom: var(--space-xs);">Supplies</h4>
                <ul style="margin: 0; padding-left: var(--space-md); font-size: 13px; color: var(--text-secondary);">
                    ${guide.supplies.map(s => `<li>${escapeHtml(s)}</li>`).join('')}
                </ul>
            </div>`
            : '';

        const tasksHtml = guide.tasks && guide.tasks.length > 0
            ? `<div style="margin-bottom: var(--space-md);">
                <h4 style="font-size: 14px; font-weight: 600; margin-bottom: var(--space-xs);">Maintenance Schedule</h4>
                ${guide.tasks.map(t => {
                    let interval = '';
                    if (t.every_wears) interval = `Every ${t.every_wears} wears`;
                    else if (t.every_days) interval = `Every ${t.every_days} days`;
                    return `<div style="display: flex; justify-content: space-between; padding: var(--space-xs) 0; border-bottom: 1px solid var(--border); font-size: 13px;">
                        <span>${escapeHtml(t.label)}</span>
                        <span style="color: var(--text-secondary);">${interval}</span>
                    </div>`;
                }).join('')}
            </div>`
            : '';

        const materialTags = (guide.materials || []).map(m => `<span class="chip small">${escapeHtml(m)}</span>`).join('');
        const categoryTags = (guide.categories || []).map(c => `<span class="chip small">${escapeHtml(c)}</span>`).join('');

        openModal(`
            <div class="modal-header">
                <span class="modal-title">${escapeHtml(guide.title)}</span>
                <button class="modal-close" onclick="closeModal()">&times;</button>
            </div>
            <div class="modal-body">
                <p style="font-size: 14px; color: var(--text-secondary); margin-bottom: var(--space-md);">${escapeHtml(guide.summary)}</p>
                <div class="chip-row" style="margin-bottom: var(--space-md);">
                    ${materialTags}
                    ${categoryTags}
                </div>
                ${sectionsHtml}
                ${suppliesHtml}
                ${tasksHtml}
            </div>
            <div class="modal-footer">
                <button class="btn btn-secondary" onclick="closeModal()">Close</button>
            </div>
        `);
    } catch (err) {
        toast(err.message, 'error');
    }
}

async function openItemCareModal(itemId) {
    try {
        const careData = await api(`/items/${itemId}/care`);
        const item = careData.item;
        const guides = careData.guides || [];
        const tasks = careData.tasks || [];
        const history = careData.history || [];

        const guidesHtml = guides.length === 0
            ? '<p class="text-muted" style="font-size: 13px;">No specific care guides matched for this item.</p>'
            : guides.map(g => `
                <div class="card" style="cursor: pointer; padding: var(--space-sm);" data-guide-id="${escapeHtml(g.id)}">
                    <div style="font-weight: 500; font-size: 14px;">${escapeHtml(g.title)}</div>
                    <div style="font-size: 12px; color: var(--text-secondary);">${escapeHtml(g.summary)}</div>
                </div>
            `).join('');

        const tasksHtml = tasks.length === 0
            ? '<p class="text-muted" style="font-size: 13px;">No maintenance tasks defined.</p>'
            : tasks.map(t => {
                let status = '';
                let statusBadge = '';
                if (t.due) {
                    statusBadge = '<span class="chip small" style="background: var(--danger); color: white;">DUE</span>';
                }
                if (t.last_done) {
                    status = `Last: ${formatDate(t.last_done)}`;
                } else {
                    status = 'Never done';
                }
                if (t.wears_since !== null && t.wears_since !== undefined) {
                    status += ` • ${t.wears_since} wears since`;
                }
                if (t.days_since !== null && t.days_since !== undefined) {
                    status += ` • ${t.days_since} days since`;
                }

                return `
                    <div style="display: flex; justify-content: space-between; align-items: center; padding: var(--space-sm) 0; border-bottom: 1px solid var(--border);">
                        <div>
                            <div style="font-size: 14px; font-weight: 500;">${escapeHtml(t.label)} ${statusBadge}</div>
                            <div style="font-size: 12px; color: var(--text-secondary);">${status}</div>
                        </div>
                        <button class="btn btn-sm btn-primary" data-log-task="${escapeHtml(t.task)}">Log</button>
                    </div>
                `;
            }).join('');

        const historyHtml = history.length === 0
            ? '<p class="text-muted" style="font-size: 13px;">No maintenance history yet.</p>'
            : history.map(h => {
                const kindBadge = h.kind && h.kind !== 'care'
                    ? `<span class="chip small" style="background: var(--accent, #6366f1); color: white;">${escapeHtml(h.kind)}</span> `
                    : '';
                const costText = h.cost && h.cost > 0 ? ` • $${Number(h.cost).toFixed(2)}` : '';
                return `
                <div style="display: flex; justify-content: space-between; align-items: center; padding: var(--space-sm) 0; border-bottom: 1px solid var(--border);">
                    <div>
                        <div style="font-size: 14px;">${kindBadge}${escapeHtml(h.task)} - ${formatDate(h.date)}${costText}</div>
                        ${h.notes ? `<div style="font-size: 12px; color: var(--text-secondary);">${escapeHtml(h.notes)}</div>` : ''}
                    </div>
                    <button class="btn btn-sm" style="color: var(--danger);" data-delete-event="${h.id}">&times;</button>
                </div>
            `;
            }).join('');

        const totalRepairCost = history.reduce((sum, h) => sum + (Number(h.cost) || 0), 0);
        const repairCostLine = totalRepairCost > 0
            ? `<p style="font-size: 12px; color: var(--text-secondary); margin-top: var(--space-xs);">Total spent on care & repairs: $${totalRepairCost.toFixed(2)}</p>`
            : '';

        const materialHint = (!item.materials || item.materials.length === 0)
            ? '<p style="font-size: 12px; color: var(--warning); margin-top: var(--space-sm);">Tip: Add materials to this item for more specific care advice.</p>'
            : '';

        openModal(`
            <div class="modal-header">
                <span class="modal-title">Care: ${escapeHtml(item.name)}</span>
                <button class="modal-close" onclick="closeModal()">&times;</button>
            </div>
            <div class="modal-body">
                <div style="margin-bottom: var(--space-md);">
                    <div style="font-size: 14px; color: var(--text-secondary);">${escapeHtml(item.category)}${item.materials && item.materials.length > 0 ? ' • ' + item.materials.join(', ') : ''}</div>
                    ${materialHint}
                </div>

                <h4 style="font-size: 16px; font-weight: 600; margin-bottom: var(--space-sm);">Matched Guides</h4>
                ${guidesHtml}

                <h4 style="font-size: 16px; font-weight: 600; margin-top: var(--space-md); margin-bottom: var(--space-sm);">Maintenance Tasks</h4>
                ${tasksHtml}

                <h4 style="font-size: 16px; font-weight: 600; margin-top: var(--space-md); margin-bottom: var(--space-sm);">History</h4>
                <button class="btn btn-sm" id="add-repair-btn" style="margin-bottom: var(--space-sm);">+ Log repair / alteration</button>
                <div id="repair-form" style="display: none; margin-bottom: var(--space-md); padding: var(--space-sm); border: 1px solid var(--border); border-radius: 8px;">
                    <input type="text" id="repair-desc" class="form-input" placeholder="What was done? (e.g. Resoled, hemmed)" style="margin-bottom: var(--space-xs); width: 100%;">
                    <div style="display: flex; gap: 8px; margin-bottom: var(--space-xs);">
                        <select id="repair-kind" class="form-input" style="flex: 1;">
                            <option value="repair">Repair</option>
                            <option value="alteration">Alteration</option>
                            <option value="professional">Professional (cobbler, dry clean, tailor)</option>
                            <option value="care">Routine care</option>
                        </select>
                        <input type="number" id="repair-cost" class="form-input" placeholder="Cost ($)" min="0" step="0.01" style="flex: 1;">
                    </div>
                    <input type="text" id="repair-notes" class="form-input" placeholder="Notes (optional)" style="margin-bottom: var(--space-xs); width: 100%;">
                    <button class="btn btn-sm btn-primary" id="repair-save-btn">Save</button>
                </div>
                ${historyHtml}
                ${repairCostLine}
            </div>
            <div class="modal-footer">
                <button class="btn btn-secondary" onclick="closeModal()">Close</button>
            </div>
        `, true);

        // Repair/alteration form toggle + save
        document.getElementById('add-repair-btn')?.addEventListener('click', () => {
            const form = document.getElementById('repair-form');
            form.style.display = form.style.display === 'none' ? 'block' : 'none';
        });
        document.getElementById('repair-save-btn')?.addEventListener('click', async () => {
            const desc = document.getElementById('repair-desc').value.trim();
            if (!desc) { toast('Enter a description', 'error'); return; }
            const kind = document.getElementById('repair-kind').value;
            const cost = parseFloat(document.getElementById('repair-cost').value) || 0;
            const notes = document.getElementById('repair-notes').value.trim();
            try {
                await api(`/items/${itemId}/care/log`, {
                    method: 'POST',
                    body: { task: desc, kind, cost, notes, date: localToday() }
                });
                toast('Logged!');
                openItemCareModal(itemId);
            } catch (err) {
                toast(err.message, 'error');
            }
        });

        // Wire up guide clicks
        document.querySelectorAll('[data-guide-id]').forEach(card => {
            card.addEventListener('click', () => {
                const guideId = card.dataset.guideId;
                openGuideModal(guideId);
            });
        });

        // Wire up Log buttons
        document.querySelectorAll('[data-log-task]').forEach(btn => {
            btn.addEventListener('click', async () => {
                const task = btn.dataset.logTask;
                const notes = prompt('Notes (optional):');
                try {
                    await api(`/items/${itemId}/care/log`, {
                        method: 'POST',
                        body: { task, date: localToday(), notes: notes || '' }
                    });
                    toast('Care task logged!');
                    openItemCareModal(itemId);
                } catch (err) {
                    toast(err.message, 'error');
                }
            });
        });

        // Wire up delete event buttons
        document.querySelectorAll('[data-delete-event]').forEach(btn => {
            btn.addEventListener('click', async () => {
                if (!confirm('Delete this care log entry?')) return;
                const eventId = parseInt(btn.dataset.deleteEvent);
                try {
                    await api(`/care/log/${eventId}`, { method: 'DELETE' });
                    toast('Care log entry deleted');
                    openItemCareModal(itemId);
                } catch (err) {
                    toast(err.message, 'error');
                }
            });
        });

    } catch (err) {
        toast(err.message, 'error');
    }
}

// ========================================
// Service Worker Registration
// ========================================

if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/sw.js')
            .then(reg => console.log('SW registered:', reg.scope))
            .catch(err => console.log('SW registration failed:', err));
    });
}

// ========================================
// App Initialization
// ========================================

function init() {
    initTabs();
    updateActiveTab();
    renderCurrentView();
}

document.addEventListener('DOMContentLoaded', init);
