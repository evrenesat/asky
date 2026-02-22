const list = document.getElementById('index-list');
const frame = document.getElementById('content-frame');
const state = {
  sort: 'date',
  group: true,
  collapsedGroups: new Set(),
  knownGroups: new Set()
};

const COPY_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="icon-copy">
  <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
  <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
</svg>`;
const CHECK_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="icon-check">
  <polyline points="20 6 9 17 4 12"></polyline>
</svg>`;

function render() {
  let items = [...ENTRIES];

  if (state.sort === 'alpha') {
    items.sort((a, b) => a.title.localeCompare(b.title));
  } else {
    items.sort((a, b) => b.iso_timestamp.localeCompare(a.iso_timestamp));
  }

  list.innerHTML = '';

  if (state.group) {
    const groupMap = new Map();
    items.forEach(item => {
      const groupId = item.session_name || item.prefix || 'Other';
      if (!groupMap.has(groupId)) groupMap.set(groupId, []);
      groupMap.get(groupId).push(item);
    });

    const renderedGroups = new Set();
    items.forEach(item => {
      const groupId = item.session_name || item.prefix || 'Other';
      const groupItems = groupMap.get(groupId);

      if (groupItems.length > 1) {
        if (!renderedGroups.has(groupId)) {
          if (!state.knownGroups.has(groupId)) {
            state.collapsedGroups.add(groupId);
            state.knownGroups.add(groupId);
          }

          const groupName = longestCommonTitlePrefix(groupItems.map(i => i.title));
          const groupEl = document.createElement('div');
          const isCollapsed = state.collapsedGroups.has(groupId);

          // Determine group copy command
          let copyCmd = '';
          const sessionItem = groupItems.find(i => i.session_id);
          if (item.session_name && sessionItem) {
            copyCmd = `asky --resume-session ${sessionItem.session_id}`;
          } else {
            const ids = groupItems.map(i => i.message_id).filter(Boolean);
            if (ids.length > 0) copyCmd = `asky --continue ${ids.join(',')}`;
          }

          const copyBtnHtml = copyCmd ? `
            <button class="copy-btn" title="Copy command" onclick="event.stopPropagation(); copyText(this, '${copyCmd}')">
              ${COPY_ICON}
            </button>
          ` : '';

          groupEl.innerHTML = `
            <div class="group-header" onclick="toggleGroup('${groupId}')">
              <span class="group-title">${groupName}</span>
              <span class="spacer"></span>
              ${copyBtnHtml}
              <span class="badge">${groupItems.length}</span>
            </div>
          `;
          if (!isCollapsed) {
            const ul = document.createElement('ul');
            groupItems.forEach(item => ul.appendChild(createItemEl(item)));
            groupEl.appendChild(ul);
          }
          list.appendChild(groupEl);
          renderedGroups.add(groupId);
        }
      } else {
        list.appendChild(createItemEl(item));
      }
    });
  } else {
    items.forEach(item => list.appendChild(createItemEl(item)));
  }
  highlightActive();
}

function createItemEl(item) {
  const li = document.createElement('li');
  li.className = 'index-item';
  const sessionHtml = item.session_name ? `<span class="session-tag">${item.session_name}</span>` : '';
  
  const copyCmd = item.message_id ? `asky --continue ${item.message_id}` : '';
  const copyBtnHtml = copyCmd ? `
    <button class="copy-btn" title="Copy: ${copyCmd}" onclick="event.stopPropagation(); copyText(this, '${copyCmd}')">
      ${COPY_ICON}
    </button>
  ` : '';

  li.innerHTML = `
    <div class="item-wrapper">
      <a href="#${item.filename}" onclick="window.location.hash='${item.filename}'; return false;">
        ${item.title}
        ${sessionHtml}
        <span class="time">${item.timestamp}</span>
      </a>
      ${copyBtnHtml}
    </div>
  `;
  return li;
}

async function copyText(btn, text) {
  try {
    await navigator.clipboard.writeText(text);
    const original = btn.innerHTML;
    btn.innerHTML = CHECK_ICON;
    btn.classList.add('copied');
    setTimeout(() => {
      btn.innerHTML = original;
      btn.classList.remove('copied');
    }, 1500);
  } catch (err) {
    console.error('Failed to copy text: ', err);
  }
}

function toggleGroup(id) {
  if (state.collapsedGroups.has(id)) state.collapsedGroups.delete(id);
  else state.collapsedGroups.add(id);
  render();
}

function highlightActive() {
  const hash = window.location.hash.substring(1);
  list.querySelectorAll('a').forEach(a => {
    if (a.getAttribute('href') === '#' + hash) a.classList.add('active');
    else a.classList.remove('active');
  });
}

document.getElementById('sort-date').onclick = (e) => {
  state.sort = 'date';
  e.target.classList.add('active');
  document.getElementById('sort-alpha').classList.remove('active');
  render();
};
document.getElementById('sort-alpha').onclick = (e) => {
  state.sort = 'alpha';
  e.target.classList.add('active');
  document.getElementById('sort-date').classList.remove('active');
  render();
};
document.getElementById('toggle-group').classList.toggle('active', state.group);
document.getElementById('toggle-group').onclick = (e) => {
  state.group = !state.group;
  e.target.classList.toggle('active', state.group);
  render();
};

function loadFromHash() {
  const hash = window.location.hash.substring(1);
  if (hash) {
    frame.src = hash;
    highlightActive();
  } else if (ENTRIES.length > 0) {
    window.location.hash = ENTRIES[0].filename;
  }
}

window.addEventListener('hashchange', loadFromHash);
window.onload = () => { loadFromHash(); render(); };

/**
 * Find the longest common word prefix among an array of titles.
 * Compares words case-insensitively but returns the prefix using the casing of the first title.
 */
function longestCommonTitlePrefix(titles) {
  if (!titles || titles.length === 0) return '';
  if (titles.length === 1) return titles[0];

  const wordsArrays = titles.map(t => t.trim().split(/\s+/));
  const firstBatch = wordsArrays[0];
  let commonCount = 0;

  for (let i = 0; i < firstBatch.length; i++) {
    const wordToMatch = firstBatch[i].toLowerCase();
    const allMatch = wordsArrays.every(words => words[i] && words[i].toLowerCase() === wordToMatch);
    if (allMatch) {
      commonCount++;
    } else {
      break;
    }
  }

  if (commonCount === 0) return 'Other';
  return firstBatch.slice(0, commonCount).join(' ');
}
