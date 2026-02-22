const list = document.getElementById('index-list');
const frame = document.getElementById('content-frame');
const state = {
  sort: 'date',
  group: true,
  collapsedGroups: new Set(),
  knownGroups: new Set()
};

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
          
          const groupEl = document.createElement('div');
          const isCollapsed = state.collapsedGroups.has(groupId);

          groupEl.innerHTML = `
            <div class="group-header" onclick="toggleGroup('${groupId}')">
              <span>${groupId}</span>
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
  li.innerHTML = `
    <a href="#${item.filename}" onclick="window.location.hash='${item.filename}'; return false;">
      ${item.title}
      ${sessionHtml}
      <span class="time">${item.timestamp}</span>
    </a>
  `;
  return li;
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
