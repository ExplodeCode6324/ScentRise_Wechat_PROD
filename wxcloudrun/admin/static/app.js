/**
 * ScentRise 后管 SPA — 路由 + API 客户端 + 页面渲染
 */

// ==================== 全局状态 ====================
const STATE = {
    admin: null,
    currentPage: ''
};

// ==================== API 客户端 ====================
const BASE = '';

async function apiFetch(url, options = {}) {
    const headers = { ...options.headers };
    // 非 FormData 请求默认 JSON
    if (!(options.body instanceof FormData)) {
        headers['Content-Type'] = 'application/json';
    }
    const resp = await fetch(BASE + url, { ...options, headers, credentials: 'same-origin' });
    const responseText = await resp.text();
    let data;
    try { data = responseText ? JSON.parse(responseText) : {}; }
    catch (_) { throw new Error(`服务返回了无效响应 (HTTP ${resp.status})`); }
    if (resp.status === 401) {
        clearSession();
        throw new Error('登录已过期');
    }
    // 后端返回 {code: 0, data: ...} 或 {code: -1, errorMsg: ...}
    if (!resp.ok || (data.code !== undefined && data.code !== 0)) {
        throw new Error(data.errorMsg || '请求失败');
    }
    return data;
}

function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>'"]/g, char => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
    }[char]));
}

function safeImageUrl(value) {
    if (!value) return '';
    try {
        const url = new URL(String(value), location.origin);
        if (url.protocol === 'https:' || url.origin === location.origin) return escapeHtml(url.href);
    } catch (_) {}
    return '';
}

function showLoadError(error) {
    const container = document.getElementById('app-content');
    container.innerHTML = '<div class="card"><p style="color:red"></p></div>';
    container.querySelector('p').textContent = '加载失败: ' + (error?.message || '未知错误');
}

// ==================== Toast ====================
function showToast(msg, type = 'success') {
    const toast = document.createElement('div');
    toast.className = 'toast toast-' + type;
    toast.textContent = msg;
    document.body.appendChild(toast);
    setTimeout(() => toast.classList.add('show'), 10);
    setTimeout(() => { toast.classList.remove('show'); setTimeout(() => toast.remove(), 300); }, 2000);
}

// ==================== 登录/登出 ====================
async function login(username, password) {
    const data = await apiFetch('/api/admin/login', {
        method: 'POST',
        body: JSON.stringify({ username, password })
    });
    STATE.admin = data.data.admin;
    document.getElementById('topbar-user').textContent = STATE.admin.username || '';
    showLogin(false);
    showApp(true);
    navigate(''); // Dashboard
}

function clearSession() {
    STATE.admin = null;
    showApp(false);
    showLogin(true);
}

async function logout() {
    try { await apiFetch('/api/admin/logout', { method: 'POST' }); }
    catch (_) {}
    clearSession();
}

function showLogin(show) {
    document.getElementById('login-page').style.display = show ? 'flex' : 'none';
}
function showApp(show) {
    document.getElementById('app-page').style.display = show ? 'flex' : 'none';
}

// ==================== 路由 ====================
const PAGES = {
    '': { title: '仪表盘', render: renderDashboard },
    'products': { title: '产品管理', render: () => renderProducts(true) },
    'products/new': { title: '添加产品', render: renderProductForm },
    'tags': { title: '标签管理', render: () => renderTags(true) },
    'tags/new': { title: '添加标签', render: renderTagForm },
    'collections': { title: '合集管理', render: () => renderCollections(true) },
    'collections/new': { title: '添加合集', render: renderCollectionForm },
    'articles': { title: '文章管理', render: () => renderArticles(true) },
    'articles/new': { title: '写文章', render: renderArticleEditor },
    'company': { title: '公司信息', render: renderCompany },
};

// ==================== 分页组件 ====================
// 各列表页的分页状态（模块级闭包）
let _prodPage = 1, _prodKeyword = '', _prodDebounce = null;
let _tagPage = 1, _tagDebounce = null;
let _colPage = 1, _colDebounce = null;
let _artPage = 1, _artDebounce = null;

/**
 * 生成分页条 HTML
 * @param {number} total 总记录数
 * @param {number} page 当前页码
 * @param {number} pageSize 每页条数
 * @param {string} goFn 翻页函数名（全局可见，如 'goProductsPage'）
 */
function renderPagination(total, page, pageSize, goFn) {
    const totalPages = Math.ceil(total / pageSize);
    let html = `<div class="pagination-bar"><span class="pagination-info">共 ${total} 条</span>`;
    if (totalPages > 1) {
        html += `<span class="pagination-info">，第 ${page}/${totalPages} 页</span>`;
        // 上一页
        if (page > 1) html += `<button class="pagination-btn" onclick="${goFn}(${page-1})">‹ 上一页</button>`;
        else html += `<button class="pagination-btn" disabled>‹ 上一页</button>`;
        // 页码（最多 7 个按钮）
        const maxBtns = 7;
        let start = Math.max(1, page - 3), end = Math.min(totalPages, start + maxBtns - 1);
        if (end - start < maxBtns - 1) start = Math.max(1, end - maxBtns + 1);
        if (start > 1) { html += `<button class="pagination-btn" onclick="${goFn}(1)">1</button>`; if (start > 2) html += '<span class="pagination-ellipsis">…</span>'; }
        for (let i = start; i <= end; i++) html += `<button class="pagination-btn${i===page?' active':''}" onclick="${goFn}(${i})">${i}</button>`;
        if (end < totalPages) { if (end < totalPages-1) html += '<span class="pagination-ellipsis">…</span>'; html += `<button class="pagination-btn" onclick="${goFn}(${totalPages})">${totalPages}</button>`; }
        // 下一页
        if (page < totalPages) html += `<button class="pagination-btn" onclick="${goFn}(${page+1})">下一页 ›</button>`;
        else html += `<button class="pagination-btn" disabled>下一页 ›</button>`;
    } else {
        html += `<span class="pagination-info">（共 1 页）</span>`;
    }
    html += '</div>';
    return html;
}

/** 通用刷新：调用 renderFn 并将结果写入 #app-content */
async function refreshContent(renderFn) {
    document.getElementById('app-content').innerHTML = '<div class="card"><p>加载中...</p></div>';
    try { document.getElementById('app-content').innerHTML = await renderFn(); }
    catch(e) { showLoadError(e); }
}

function navigate(hash) {
    STATE.currentPage = hash;
    location.hash = hash;
    const page = PAGES[hash];
    if (!page) {
        // 处理 collections/:id/products（合集产品管理）
        const cpMatch = hash.match(/^collections\/(\d+)\/products$/);
        if (cpMatch) {
            const colId = parseInt(cpMatch[1]);
            document.getElementById('current-page-title').textContent = '合集产品管理';
            document.getElementById('app-content').innerHTML = '<div class="card"><p>加载中...</p></div>';
            renderCollectionProducts(colId).then(html => {
                document.getElementById('app-content').innerHTML = html;
            }).catch(e => {
                showLoadError(e);
            });
            highlightNav('collections');
            return;
        }
        // 处理动态路由: products/{id}, tags/{id}, collections/{id}, articles/{id}
        const match = hash.match(/^(products|tags|collections|articles)\/(\d+)$/);
        if (match) {
            const [, type, id] = match;
            const dynamicPages = {
                'products': { title: '编辑产品', render: (ctx) => renderProductForm(parseInt(id)) },
                'tags': { title: '编辑标签', render: (ctx) => renderTagForm(parseInt(id)) },
                'collections': { title: '编辑合集', render: (ctx) => renderCollectionForm(parseInt(id)) },
                'articles': { title: '编辑文章', render: (ctx) => renderArticleEditor(parseInt(id)) },
            };
            const dp = dynamicPages[type];
            if (dp) {
                document.getElementById('current-page-title').textContent = dp.title;
                document.getElementById('app-content').innerHTML = '<div class="card"><p>加载中...</p></div>';
                dp.render().then(html => {
                    document.getElementById('app-content').innerHTML = html;
                }).catch(e => {
                    showLoadError(e);
                });
                highlightNav(type);
                return;
            }
        }
        document.getElementById('app-content').innerHTML = '<div class="card"><p>页面不存在</p></div>';
        return;
    }
    document.getElementById('current-page-title').textContent = page.title;
    document.getElementById('app-content').innerHTML = '<div class="card"><p>加载中...</p></div>';
    page.render().then(html => {
        document.getElementById('app-content').innerHTML = html;
    }).catch(e => {
        showLoadError(e);
    });
    // 高亮导航
    const navKey = hash.split('/')[0];
    highlightNav(navKey);
}

function highlightNav(key) {
    document.querySelectorAll('.sidebar-nav a').forEach(a => {
        a.classList.toggle('active', a.dataset.nav === key);
    });
}

window.addEventListener('hashchange', () => {
    const hash = location.hash.slice(1);
    if (STATE.admin) navigate(hash);
});

// ==================== 页面渲染（基础 stub） ====================

async function renderDashboard() {
    const [productsData, articlesData, collectionsData, tagsData] = await Promise.all([
        apiFetch('/api/admin/products?page_size=1'),
        apiFetch('/api/admin/articles?page=1&page_size=5&status=published'),
        apiFetch('/api/admin/collections'),
        apiFetch('/api/admin/tags'),
    ]);
    const html = `
        <div class="stat-cards">
            <div class="stat-card"><div class="stat-num">${productsData.data.total || 0}</div><div class="stat-label">产品总数</div></div>
            <div class="stat-card"><div class="stat-num">${articlesData.data.total || 0}</div><div class="stat-label">已发布文章</div></div>
            <div class="stat-card"><div class="stat-num">${collectionsData.data.total || 0}</div><div class="stat-label">合集数</div></div>
            <div class="stat-card"><div class="stat-num">${tagsData.data.total || 0}</div><div class="stat-label">标签数</div></div>
        </div>
        <div class="card">
            <div class="card-title">最近文章</div>
            ${(articlesData.data.list || []).map(a => `<div style="padding:6px 0;border-bottom:1px solid #eee;font-size:13px">${escapeHtml(a.title)}</div>`).join('') || '<p style="color:#999">暂无文章</p>'}
        </div>`;
    return html;
}

// --- 产品 ---
// --- 产品列表（分页 + 搜索） ---

// 翻页 / 搜索入口（全局可见，供 onclick 和 oninput 调用）
function goProductsPage(pg) { _prodPage = pg; refreshContent(() => renderProducts(false)); }
function searchProducts() {
    clearTimeout(_prodDebounce);
    _prodDebounce = setTimeout(() => {
        _prodKeyword = (document.getElementById('search-input')?.value || '').trim();
        _prodPage = 1;
        refreshContent(() => renderProducts(false));
    }, 400);
}

async function renderProducts(reset = false) {
    if (reset) { _prodPage = 1; _prodKeyword = ''; }
    const params = new URLSearchParams({ page: _prodPage, page_size: 20 });
    if (_prodKeyword) params.set('keyword', _prodKeyword);
    const data = await apiFetch('/api/admin/products?' + params);
    const cats = reset ? await apiFetch('/api/categories') : { data: [] };  // 仅首次加载分类（用于后续引用）
    const rows = (data.data.list || []).map(p => `
        <tr>
            <td>${safeImageUrl(p.productImage) ? `<img src="${safeImageUrl(p.productImage)}" class="img-thumb" alt="">` : '-'}</td>
            <td>${escapeHtml(p.productModel || '-')}</td>
            <td>${escapeHtml(p.productName || '-')}</td>
            <td>${escapeHtml(p.productEnglishName || '-')}</td>
            <td>${escapeHtml(p.productSeries || '-')}</td>
            <td>${(p.tags || []).map(t => {
                const cls = t.category === '产品系列' ? 'badge badge-primary' : 'badge badge-secondary';
                return `<span class="${cls}">${escapeHtml(t.name)}</span>`;
            }).join(' ')}</td>
            <td><span class="badge ${p.isActive ? 'badge-success' : 'badge-warning'}">${p.isActive ? '上架' : '下架'}</span></td>
            <td>
                <button class="btn btn-sm btn-outline" onclick="navigate('products/${p.id}')">编辑</button>
                <button class="btn btn-sm btn-danger" onclick="delProduct(${p.id})">删除</button>
            </td>
        </tr>`).join('');

    return `
        <div class="page-header">
            <h2>产品管理</h2>
            <div>
                <button class="btn btn-primary" onclick="navigate('products/new')">+ 添加产品</button>
                <button class="btn btn-outline" onclick="document.getElementById('import-file').click()" style="margin-left:8px">📥 导入 Excel</button>
                <input type="file" id="import-file" accept=".xlsx" style="display:none" onchange="importExcel(this)">
            </div>
        </div>
        <div class="card">
            <input type="text" id="search-input" placeholder="搜索产品名称/型号..." value="${escapeHtml(_prodKeyword||'')}"
                style="width:200px;padding:6px 10px;border:1px solid #ddd;border-radius:4px;margin-bottom:12px"
                oninput="searchProducts()">
            <table><thead><tr>
                <th>缩略图</th><th>型号</th><th>产品名</th><th>英文名</th><th>系列</th><th>标签</th><th>状态</th><th>操作</th>
            </tr></thead><tbody>${rows}</tbody></table>
            ${renderPagination(data.data.total, data.data.page, data.data.pageSize, 'goProductsPage')}
        </div>`;
}

async function renderProductForm(id) {
    const isEdit = !!id;
    let p = { productSeries:'', productModel:'', productName:'', productEnglishName:'', productDesc:'', isActive:true, sortOrder:0, categoryId:'', tags:[], images:[] };
    if (isEdit) {
        const data = await apiFetch('/api/admin/products/' + id);
        p = data.data;
    }
    const [cats, tags, cols] = await Promise.all([
        apiFetch('/api/categories'),
        apiFetch('/api/tags'),
        apiFetch('/api/collections'),
    ]);
    const catOpts = (cats.data||[]).map(c => `<option value="${Number(c.id)}" ${p.categoryId==c.id?'selected':''}>${escapeHtml(c.name)}</option>`).join('');
    const seriesTags = (tags.data||[]).filter(t => t.category === '产品系列');
    const appTags = (tags.data||[]).filter(t => t.category !== '产品系列');
    const selectedCollectionIds = new Set(p.collectionIds || []);
    const colOpts = (cols.data||[]).map(c => `<option value="${Number(c.id)}" ${selectedCollectionIds.has(c.id)?'selected':''}>${escapeHtml(c.name)}</option>`).join('');
    const selectedTagIds = (p.tags||[]).map(t=>t.id);
    const seriesCheckboxes = seriesTags.map(t => {
        const checked = selectedTagIds.includes(t.id) ? 'checked' : '';
        return `<label class="tag-checkbox"><input type="checkbox" name="tagIds" value="${Number(t.id)}" ${checked}> ${escapeHtml(t.name)}</label>`;
    }).join('');
    const appCheckboxes = appTags.map(t => {
        const checked = selectedTagIds.includes(t.id) ? 'checked' : '';
        return `<label class="tag-checkbox"><input type="checkbox" name="tagIds" value="${Number(t.id)}" ${checked}> ${escapeHtml(t.name)}</label>`;
    }).join('');
    const imagePreviews = (p.images||[]).map(img => `
        <div class="image-item">
            <img src="${safeImageUrl(img.imageUrl)}" class="${img.isPrimary?'primary':''}" alt="">
            ${img.isPrimary ? '<span class="primary-badge">主图</span>' : ''}
            <button class="btn-remove" onclick="delProductImage(${p.id||0},${img.id})">×</button>
        </div>`).join('');

    return `
        <div class="page-header">
            <h2>${isEdit?'编辑':'添加'}产品</h2>
            <button class="btn btn-outline" onclick="navigate('products')">← 返回列表</button>
        </div>
        <div class="card">
            <form id="product-form" onsubmit="saveProduct(event,${isEdit?id:0})">
                <div class="form-group"><label>产品系列</label><select name="categoryId">${catOpts}</select></div>
                <div class="form-group"><label>产品型号 *</label><input name="productModel" value="${escapeHtml(p.productModel||'')}" ${isEdit?'readonly':''} required></div>
                <div class="form-group"><label>产品名称 *</label><input name="productName" value="${escapeHtml(p.productName||'')}" required></div>
                <div class="form-group"><label>英文名称</label><input name="productEnglishName" value="${escapeHtml(p.productEnglishName||'')}" placeholder="选填"></div>
                <div class="form-group"><label>产品描述</label><textarea name="productDesc">${escapeHtml(p.productDesc||'')}</textarea></div>
                <div class="form-group">
                  <label>标签 - 产品系列</label>
                  <div class="checkbox-group">${seriesCheckboxes || '<span style="color:#999;font-size:13px">暂无系列标签</span>'}</div>
                </div>
                <div class="form-group">
                  <label>标签 - 适用范围</label>
                  <div class="checkbox-group">${appCheckboxes || '<span style="color:#999;font-size:13px">暂无适用范围标签</span>'}</div>
                </div>
                <div class="form-group"><label>所属合集</label><select name="collectionIds" multiple style="min-height:100px">${colOpts}</select></div>
                <div class="form-group"><label>排序</label><input name="sortOrder" type="number" value="${p.sortOrder||0}"></div>
                <div class="form-group"><label><input type="checkbox" name="isActive" ${p.isActive!==false?'checked':''}> 上架</label></div>
                <button type="submit" class="btn btn-primary">保存</button>
            </form>
        </div>
        ${isEdit ? `
        <div class="card" style="margin-top:16px">
            <div class="card-title">产品图片</div>
            <div class="image-list">${imagePreviews || '<span style="color:#999">暂无图片</span>'}</div>
            <div style="margin-top:12px">
                <label style="margin-right:8px"><input type="radio" name="imgType" value="main" checked> 主图</label>
                <label style="margin-right:8px"><input type="radio" name="imgType" value="detail"> 详情图</label>
                <input type="file" id="product-img-file" accept="image/*" style="margin-left:8px">
                <button class="btn btn-sm btn-primary" onclick="uploadProductImage(${id})">上传</button>
            </div>
        </div>` : '<p style="color:#999;margin-top:8px">保存后可上传图片</p>'}
    `;
}

// --- 标签列表（分页） ---

function goTagsPage(pg) { _tagPage = pg; refreshContent(() => renderTags(false)); }

async function renderTags(reset = false) {
    if (reset) _tagPage = 1;
    const data = await apiFetch(`/api/admin/tags?page=${_tagPage}&page_size=20`);
    const rows = (data.data.list || []).map(t => `
        <tr>
            <td>${safeImageUrl(t.icon) ? `<img src="${safeImageUrl(t.icon)}" class="img-thumb" alt="">` : '-'}</td>
            <td>${escapeHtml(t.name)}</td>
            <td>${escapeHtml(t.category||'-')}</td>
            <td>${safeImageUrl(t.bannerImage) ? `<img src="${safeImageUrl(t.bannerImage)}" style="width:80px;height:30px;object-fit:cover;border-radius:2px" alt="">` : '-'}</td>
            <td>${t.sortOrder||0}</td>
            <td>
                <button class="btn btn-sm btn-outline" onclick="navigate('tags/${t.id}')">编辑</button>
                <button class="btn btn-sm btn-danger" onclick="delTag(${t.id})">删除</button>
            </td>
        </tr>`).join('');
    return `
        <div class="page-header"><h2>标签管理</h2><button class="btn btn-primary" onclick="navigate('tags/new')">+ 添加标签</button></div>
        <div class="card">
            <table><thead><tr><th>图标</th><th>名称</th><th>分类</th><th>横幅</th><th>排序</th><th>操作</th></tr></thead>
            <tbody>${rows}</tbody></table>
            ${renderPagination(data.data.total, data.data.page, data.data.pageSize, 'goTagsPage')}
        </div>`;
}

async function renderTagForm(id) {
    const isEdit = !!id;
    let t = { name:'', category:'适用产品', sortOrder:0, icon:'', bannerImage:'' };
    if (isEdit) { const data = await apiFetch('/api/admin/tags/' + id); t = data.data; }
    return `
        <div class="page-header"><h2>${isEdit?'编辑':'添加'}标签</h2><button class="btn btn-outline" onclick="navigate('tags')">← 返回</button></div>
        <div class="card">
            <form onsubmit="saveTag(event,${id||0})">
                <div class="form-group"><label>名称 *</label><input name="name" value="${escapeHtml(t.name||'')}" required></div>
                <div class="form-group"><label>分类</label><select name="category">
                    ${['产品系列','适用产品'].map(c=>`<option ${t.category==c?'selected':''}>${c}</option>`).join('')}
                </select></div>
                <div class="form-group"><label>排序</label><input name="sortOrder" type="number" value="${t.sortOrder||0}"></div>
                <button type="submit" class="btn btn-primary">保存</button>
            </form>
            ${isEdit ? `
            <div style="margin-top:16px">
                <div style="margin-bottom:8px"><strong>图标</strong> ${safeImageUrl(t.icon)?`<img src="${safeImageUrl(t.icon)}" style="width:30px;height:30px;vertical-align:middle;margin-left:8px" alt="">`:''}</div>
                <input type="file" id="tag-icon-file" accept="image/*"> <button class="btn btn-sm btn-primary" onclick="uploadTagImage(${id},'icon')">上传图标</button>
                <div style="margin-top:12px"><strong>横幅</strong> ${safeImageUrl(t.bannerImage)?`<img src="${safeImageUrl(t.bannerImage)}" style="width:120px;height:40px;vertical-align:middle;margin-left:8px;object-fit:cover" alt="">`:''}</div>
                <input type="file" id="tag-banner-file" accept="image/*"> <button class="btn btn-sm btn-primary" onclick="uploadTagImage(${id},'banner')">上传横幅</button>
            </div>` : '<p style="color:#999;margin-top:8px">保存后可上传图标/横幅</p>'}
        </div>`;
}

// --- 合集列表（分页） ---

function goCollectionsPage(pg) { _colPage = pg; refreshContent(() => renderCollections(false)); }

async function renderCollections(reset = false) {
    if (reset) _colPage = 1;
    const data = await apiFetch(`/api/admin/collections?page=${_colPage}&page_size=20`);
    const rows = (data.data.list || []).map(c => `
        <tr>
            <td>${safeImageUrl(c.coverImage)?`<img src="${safeImageUrl(c.coverImage)}" class="img-thumb" alt="">`:'-'}</td>
            <td>${escapeHtml(c.name)}</td>
            <td><span class="badge ${c.isCarousel?'badge-success':'badge-secondary'}">${c.isCarousel?'✓':'✗'}</span></td>
            <td>${(c.products||[]).length}</td>
            <td>${c.sortOrder||0}</td>
            <td>
                <button class="btn btn-sm btn-outline" onclick="navigate('collections/${c.id}')">编辑</button>
                <button class="btn btn-sm btn-outline" onclick="navigate('collections/${c.id}/products')">产品</button>
                <button class="btn btn-sm btn-danger" onclick="delCollection(${c.id})">删除</button>
            </td>
        </tr>`).join('');
    return `
        <div class="page-header"><h2>合集管理</h2><button class="btn btn-primary" onclick="navigate('collections/new')">+ 添加合集</button></div>
        <div class="card"><table><thead><tr><th>封面</th><th>名称</th><th>轮播</th><th>产品数</th><th>排序</th><th>操作</th></tr></thead><tbody>${rows}</tbody></table>
        ${renderPagination(data.data.total, data.data.page, data.data.pageSize, 'goCollectionsPage')}
        </div>`;
}

async function renderCollectionForm(id) {
    const isEdit = !!id;
    let c = { name:'', description:'', isCarousel:false, carouselSort:0, sortOrder:0, coverImage:'' };
    if (isEdit) { const data = await apiFetch('/api/admin/collections/' + id); c = data.data; }
    return `
        <div class="page-header"><h2>${isEdit?'编辑':'添加'}合集</h2><button class="btn btn-outline" onclick="navigate('collections')">← 返回</button></div>
        <div class="card">
            <form onsubmit="saveCollection(event,${id||0})">
                <div class="form-group"><label>名称 *</label><input name="name" value="${escapeHtml(c.name||'')}" required></div>
                <div class="form-group"><label>描述</label><textarea name="description">${escapeHtml(c.description||'')}</textarea></div>
                <div class="form-group"><label><input type="checkbox" name="isCarousel" ${c.isCarousel?'checked':''}> 首页轮播</label></div>
                <div class="form-group"><label>轮播排序</label><input name="carouselSort" type="number" value="${c.carouselSort||0}"></div>
                <div class="form-group"><label>排序</label><input name="sortOrder" type="number" value="${c.sortOrder||0}"></div>
                <button type="submit" class="btn btn-primary">保存</button>
            </form>
            ${isEdit ? `
            <div style="margin-top:12px"><strong>封面</strong> ${safeImageUrl(c.coverImage)?`<img src="${safeImageUrl(c.coverImage)}" class="img-preview" alt="">`:''}
            <div><input type="file" id="col-cover-file" accept="image/*"> <button class="btn btn-sm btn-primary" onclick="uploadCollectionCover(${id})">上传封面</button></div></div>` : ''}
        </div>`;
}

// --- 合集产品管理 ---
async function renderCollectionProducts(colId) {
    const data = await apiFetch('/api/admin/collections/' + colId + '/products');
    const col = data.data.collection;
    const linked = data.data.linkedProducts || [];
    const allProds = data.data.allProducts || [];
    const linkedIds = new Set(linked.map(p => p.id));

    const leftRows = allProds.map(p => {
        const checked = linkedIds.has(p.id) ? 'checked' : '';
        return `<label class="cp-item ${checked?'selected':''}">
            <input type="checkbox" name="cp_product" value="${p.id}" ${checked} onchange="this.parentElement.classList.toggle('selected',this.checked)">
            <span class="cp-info"><strong>${escapeHtml(p.productName||'-')}</strong> <small>${escapeHtml(p.productModel||'')}</small></span>
            <span class="cp-series">${escapeHtml(p.productSeries||'')}</span>
        </label>`;
    }).join('');

    const rightRows = linked.map((p, i) => `
        <div class="cp-linked-item" data-pid="${p.id}">
            <span class="cp-order">${i+1}</span>
            <span class="cp-info"><strong>${escapeHtml(p.productName||'-')}</strong> <small>${escapeHtml(p.productModel||'')}</small></span>
            <button class="btn btn-sm" onclick="removeLinkedProduct(this, ${p.id})" title="移除">×</button>
        </div>`).join('') || '<p style="color:#999;padding:12px">暂未关联产品</p>';

    return `
        <div class="page-header">
            <h2>合集产品管理：${escapeHtml(col.name)}</h2>
            <button class="btn btn-outline" onclick="navigate('collections')">← 返回合集列表</button>
        </div>
        <div class="cp-panel">
            <div class="cp-left card">
                <div class="card-title">可选产品 <span style="font-weight:normal;font-size:12px;color:#999">(勾选后保存)</span></div>
                <input type="text" class="cp-search" placeholder="搜索产品..." oninput="filterCollectionProducts(this)">
                <div class="cp-list" id="cp-all-list">${leftRows}</div>
            </div>
            <div class="cp-right card">
                <div class="card-title">已选产品 <span style="font-weight:normal;font-size:12px;color:#999" id="cp-count">${linked.length} 个</span></div>
                <div class="cp-linked-list" id="cp-linked-list">${rightRows}</div>
            </div>
        </div>
        <div style="margin-top:16px;text-align:center">
            <button class="btn btn-primary" onclick="saveCollectionProducts(${colId})" style="min-width:120px">💾 保存</button>
        </div>`;
}

async function saveCollectionProducts(colId) {
    const checked = document.querySelectorAll('input[name="cp_product"]:checked');
    const productIds = Array.from(checked).map(cb => parseInt(cb.value));
    await apiFetch('/api/admin/collections/' + colId + '/products', {
        method: 'PUT',
        body: JSON.stringify({ product_ids: productIds })
    });
    showToast('已保存 (' + productIds.length + ' 个产品)');
    navigate('collections/' + colId + '/products');
}

function removeLinkedProduct(btn, pid) {
    const cb = document.querySelector('input[name="cp_product"][value="' + pid + '"]');
    if (cb) { cb.checked = false; cb.parentElement.classList.remove('selected'); }
    btn.parentElement.remove();
    updateLinkedCount();
}

function filterCollectionProducts(input) {
    const kw = input.value.toLowerCase();
    document.querySelectorAll('#cp-all-list .cp-item').forEach(item => {
        const text = item.textContent.toLowerCase();
        item.style.display = text.includes(kw) ? '' : 'none';
    });
}

function updateLinkedCount() {
    const count = document.querySelectorAll('#cp-linked-list .cp-linked-item').length;
    const el = document.getElementById('cp-count');
    if (el) el.textContent = count + ' 个';
}

// --- 文章列表（分页） ---

function goArticlesPage(pg) { _artPage = pg; refreshContent(() => renderArticles(false)); }

async function renderArticles(reset = false) {
    if (reset) _artPage = 1;
    const data = await apiFetch(`/api/admin/articles?page=${_artPage}&page_size=20&status=all`);
    const rows = (data.data.list||[]).map(a => `
        <tr>
            <td>${safeImageUrl(a.coverImage)?`<img src="${safeImageUrl(a.coverImage)}" class="img-thumb" alt="">`:'-'}</td>
            <td><a href="#articles/${Number(a.id)}">${escapeHtml(a.title)}</a></td>
            <td>${escapeHtml(a.author||'-')}</td>
            <td><span class="badge ${a.isPublished?'badge-success':'badge-warning'}">${a.isPublished?'已发布':'草稿'}</span></td>
            <td>${escapeHtml(a.publishedAt||'-')}</td>
            <td>
                <button class="btn btn-sm btn-outline" onclick="navigate('articles/${a.id}')">编辑</button>
                <button class="btn btn-sm btn-danger" onclick="delArticle(${a.id})">删除</button>
            </td>
        </tr>`).join('');
    return `
        <div class="page-header"><h2>文章管理</h2><button class="btn btn-primary" onclick="navigate('articles/new')">+ 写文章</button></div>
        <div class="card"><table><thead><tr><th>封面</th><th>标题</th><th>作者</th><th>状态</th><th>发布时间</th><th>操作</th></tr></thead><tbody>${rows}</tbody></table>
        ${renderPagination(data.data.total, data.data.page, data.data.pageSize, 'goArticlesPage')}
        </div>`;
}

async function renderArticleEditor(id) {
    const isEdit = !!id;
    let a = { title:'', author:'', content:'', coverImage:'', isPublished:false, sortOrder:0 };
    if (isEdit) { const data = await apiFetch('/api/admin/articles/'+id); a = data.data; }
    return `
        <div class="page-header"><h2>${isEdit?'编辑':'写'}文章</h2><button class="btn btn-outline" onclick="navigate('articles')">← 返回</button></div>
        <div class="card">
            <form onsubmit="saveArticle(event,${id||0})">
                <div class="form-group"><label>标题 *</label><input name="title" value="${escapeHtml(a.title||'')}" required></div>
                <div class="form-group"><label>作者</label><input name="author" value="${escapeHtml(a.author||'')}"></div>
                <div class="form-group"><label>正文 *（支持安全的基础 HTML）</label>
                    <textarea name="content" rows="16" required>${escapeHtml(a.content||'')}</textarea>
                </div>
                <div class="form-group"><label>排序</label><input name="sortOrder" type="number" value="${a.sortOrder||0}"></div>
                <div class="form-group"><label><input type="radio" name="isPublished" value="1" ${a.isPublished?'checked':''}> 发布</label>
                <label style="margin-left:16px"><input type="radio" name="isPublished" value="0" ${!a.isPublished?'checked':''}> 草稿</label></div>
                <button type="submit" class="btn btn-primary">保存</button>
            </form>
            ${isEdit ? `
            <div style="margin-top:12px"><strong>封面</strong> ${safeImageUrl(a.coverImage)?`<img src="${safeImageUrl(a.coverImage)}" class="img-preview" alt="">`:''}
            <div><input type="file" id="article-cover-file" accept="image/*"> <button class="btn btn-sm btn-primary" onclick="uploadArticleCover(${id})">上传封面</button></div></div>` : ''}
        </div>`;
}

// --- 公司信息 ---
async function renderCompany() {
    let c = {};
    try { const data = await apiFetch('/api/admin/company'); c = data.data || {}; } catch(e) {}
    return `
        <div class="page-header"><h2>公司信息</h2></div>
        <div class="card">
            <form onsubmit="saveCompany(event)">
                <div class="form-group"><label>公司名称</label><input name="name" value="${escapeHtml(c.name||'')}"></div>
                <div class="form-group"><label>公司简介</label><textarea name="intro">${escapeHtml(c.intro||'')}</textarea></div>
                <div class="form-group"><label>联系电话</label><input name="phone" value="${escapeHtml(c.phone||'')}"></div>
                <div class="form-group"><label>微信号</label><input name="wechatId" value="${escapeHtml(c.wechatId||'')}"></div>
                <div class="form-group"><label>邮箱</label><input name="email" type="email" value="${escapeHtml(c.email||'')}"></div>
                <div class="form-group"><label>地址</label><input name="address" value="${escapeHtml(c.address||'')}"></div>
                <div class="form-group"><label>营业时间</label><input name="businessHours" value="${escapeHtml(c.businessHours||'')}"></div>
                <button type="submit" class="btn btn-primary">保存</button>
            </form>
            <div style="margin-top:12px"><strong>Logo</strong> ${safeImageUrl(c.logo)?`<img src="${safeImageUrl(c.logo)}" class="img-preview" alt="">`:''}
            <div><input type="file" id="company-logo-file" accept="image/*"> <button class="btn btn-sm btn-primary" onclick="uploadCompanyLogo()">上传 Logo</button></div></div>
            <div style="margin-top:12px"><strong>微信二维码</strong> ${safeImageUrl(c.wechatQr)?`<img src="${safeImageUrl(c.wechatQr)}" class="img-preview" alt="">`:''}
            <div><input type="file" id="company-qr-file" accept="image/*"> <button class="btn btn-sm btn-primary" onclick="uploadCompanyQR()">上传二维码</button></div></div>
        </div>`;
}

// ==================== 操作函数 ====================
async function saveProduct(e, id) {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = {
        categoryId: parseInt(fd.get('categoryId')) || null,
        productModel: fd.get('productModel'),
        productName: fd.get('productName'),
        productEnglishName: fd.get('productEnglishName') || '',
        productDesc: fd.get('productDesc'),
        isActive: fd.get('isActive') === 'on',
        sortOrder: parseInt(fd.get('sortOrder')) || 0,
        tagIds: Array.from(e.target.querySelectorAll('input[name="tagIds"]:checked')).map(o=>parseInt(o.value)),
        collectionIds: Array.from(e.target.querySelector('select[name="collectionIds"]').selectedOptions).map(o=>parseInt(o.value)),
    };
    const method = id ? 'PUT' : 'POST';
    const url = id ? '/api/admin/products/' + id : '/api/admin/products';
    await apiFetch(url, { method, body: JSON.stringify(body) });
    showToast(id ? '产品已更新' : '产品已创建');
    navigate('products');
}

async function delProduct(id) {
    if (!confirm('确定删除该产品？关联的标签/合集关系及云存储图片将被清理。')) return;
    await apiFetch('/api/admin/products/' + id, { method: 'DELETE' });
    showToast('已删除');
    navigate('products');
}

async function saveTag(e, id) {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = { name: fd.get('name'), category: fd.get('category'), sortOrder: parseInt(fd.get('sortOrder'))||0 };
    const method = id ? 'PUT' : 'POST';
    const url = id ? '/api/admin/tags/' + id : '/api/admin/tags';
    const data = await apiFetch(url, { method, body: JSON.stringify(body) });
    showToast(id ? '标签已更新' : '标签已创建');
    if (!id) navigate('tags/' + data.data.id);
    else navigate('tags');
}

async function delTag(id) { if(!confirm('确定删除标签？'))return; await apiFetch('/api/admin/tags/'+id,{method:'DELETE'}); showToast('已删除'); navigate('tags'); }

async function uploadTagImage(tagId, type) {
    try {
        const fileInput = document.getElementById(type==='icon'?'tag-icon-file':'tag-banner-file');
        if (!fileInput.files[0]) return showToast('请选择文件', 'error');
        const fd = new FormData(); fd.append('file', fileInput.files[0]); fd.append('type', type);
        await apiFetch('/api/admin/tags/' + tagId + '/image', { method: 'POST', body: fd });
        showToast('上传成功'); navigate('tags/' + tagId);
    } catch(e) { showToast(e.message, 'error'); }
}

async function saveCollection(e, id) {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = { name: fd.get('name'), description: fd.get('description'), isCarousel: fd.get('isCarousel')==='on', carouselSort: parseInt(fd.get('carouselSort'))||0, sortOrder: parseInt(fd.get('sortOrder'))||0 };
    const method = id ? 'PUT' : 'POST';
    const url = id ? '/api/admin/collections/'+id : '/api/admin/collections';
    await apiFetch(url, { method, body: JSON.stringify(body) });
    showToast(id?'合集已更新':'合集已创建'); navigate('collections');
}

async function delCollection(id) { if(!confirm('确定删除合集？'))return; await apiFetch('/api/admin/collections/'+id,{method:'DELETE'}); showToast('已删除'); navigate('collections'); }
async function uploadCollectionCover(id) {
    try {
        const f = document.getElementById('col-cover-file'); if(!f.files[0]) return showToast('请选择文件','error');
        const fd = new FormData(); fd.append('file', f.files[0]);
        await apiFetch('/api/admin/collections/'+id+'/image',{method:'POST',body:fd});
        showToast('上传成功'); navigate('collections/'+id);
    } catch(e) { showToast(e.message, 'error'); }
}

async function saveArticle(e, id) {
    e.preventDefault();
    const fd = new FormData(e.target);
    const content = fd.get('content') || '';
    const body = { title: fd.get('title'), author: fd.get('author'), content, isPublished: fd.get('isPublished')==='1', sortOrder: parseInt(fd.get('sortOrder'))||0 };
    const method = id ? 'PUT' : 'POST';
    const url = id ? '/api/admin/articles/'+id : '/api/admin/articles';
    await apiFetch(url, { method, body: JSON.stringify(body) });
    showToast(id?'文章已更新':'文章已创建'); navigate('articles');
}

async function delArticle(id) { if(!confirm('确定删除文章？'))return; await apiFetch('/api/admin/articles/'+id,{method:'DELETE'}); showToast('已删除'); navigate('articles'); }
async function uploadArticleCover(id) {
    try {
        const f = document.getElementById('article-cover-file'); if(!f.files[0]) return showToast('请选择文件','error');
        const fd = new FormData(); fd.append('file', f.files[0]);
        await apiFetch('/api/admin/articles/'+id+'/image',{method:'POST',body:fd});
        showToast('上传成功'); navigate('articles/'+id);
    } catch(e) { showToast(e.message, 'error'); }
}

async function saveCompany(e) {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = { name:fd.get('name'), intro:fd.get('intro'), phone:fd.get('phone'), wechatId:fd.get('wechatId'), email:fd.get('email'), address:fd.get('address'), businessHours:fd.get('businessHours') };
    await apiFetch('/api/admin/company',{method:'PUT',body:JSON.stringify(body)});
    showToast('保存成功');
}

async function uploadCompanyLogo() {
    try {
        const f = document.getElementById('company-logo-file'); if(!f.files[0]) return showToast('请选择文件','error');
        const fd = new FormData(); fd.append('file', f.files[0]);
        await apiFetch('/api/admin/company/logo',{method:'POST',body:fd});
        showToast('上传成功'); navigate('company');
    } catch(e) { showToast(e.message, 'error'); }
}

async function uploadCompanyQR() {
    try {
        const f = document.getElementById('company-qr-file'); if(!f.files[0]) return showToast('请选择文件','error');
        const fd = new FormData(); fd.append('file', f.files[0]);
        await apiFetch('/api/admin/company/qr',{method:'POST',body:fd});
        showToast('上传成功'); navigate('company');
    } catch(e) { showToast(e.message, 'error'); }
}

// ==================== 产品图片上传 ====================
async function uploadProductImage(productId) {
    try {
        const fileInput = document.getElementById('product-img-file');
        if (!fileInput || !fileInput.files[0]) return showToast('请选择文件', 'error');
        const imgType = document.querySelector('input[name="imgType"]:checked');
        const imageType = imgType ? imgType.value : 'main';
        const fd = new FormData();
        fd.append('file', fileInput.files[0]);
        fd.append('image_type', imageType);
        await apiFetch('/api/admin/products/' + productId + '/images', { method: 'POST', body: fd });
        showToast('上传成功');
        navigate('products/' + productId);
    } catch(e) { showToast(e.message, 'error'); }
}

async function delProductImage(productId, imageId) {
    try {
        if (!confirm('确定删除该图片？')) return;
        await apiFetch('/api/admin/products/' + productId + '/images/' + imageId, { method: 'DELETE' });
        showToast('已删除');
        navigate('products/' + productId);
    } catch(e) { showToast(e.message, 'error'); }
}

// ==================== 产品搜索 ====================
// searchProducts() 已在产品列表区块定义（含 debounce + 服务端搜索），此处保留作为别名

// ==================== Excel 导入 ====================
async function importExcel(input) {
    if (!input.files[0]) return;
    if (input.files[0].size > 10 * 1024 * 1024) {
        input.value = '';
        return showToast('Excel 文件不能超过 10MB', 'error');
    }
    try {
        const reader = new FileReader();
        reader.onload = async function(e) {
            try {
                const data = new Uint8Array(e.target.result);
                const workbook = XLSX.read(data, {type: 'array'});
                const sheet = workbook.Sheets[workbook.SheetNames[0]];
                const headerRow = (XLSX.utils.sheet_to_json(sheet, { header: 1, range: 0 })[0] || [])
                    .map(name => String(name).trim());
                // 第一行只作为字段名，数据固定从第二行开始读取。
                const rows = XLSX.utils.sheet_to_json(sheet, {
                    header: headerRow, range: 1, defval: '', blankrows: false
                });
                const TAG_COLUMNS = ['烘培', '糖果', '饮料', '炒货', '乳品', '膨化', '电子烟'];
                const tagsProvided = headerRow.some(name => name === '标签' || name === 'tags' || TAG_COLUMNS.includes(name));
                const marked = value => value === true || value === 1 || ['√', '✓', 'v', 'V', '1', '是', 'true', 'TRUE'].includes(String(value).trim());
                const mapped = rows.map((r, index) => {
                    const tags = [];
                    TAG_COLUMNS.forEach(col => {
                        if (marked(r[col])) tags.push(col);
                    });
                    const legacyTags = (r['标签'] || r['tags'] || '').toString().split(/[,，;；]/).map(t => t.trim()).filter(Boolean);
                    return {
                        excelRow: index + 2,
                        productSeries: r['产品系列'] || r['productSeries'] || '',
                        productName: r['产品名称'] || r['名称'] || r['productName'] || '',
                        productEnglishName: r['英文名称'] || r['productEnglishName'] || '',
                        productModel: r['产品型号'] || r['型号'] || r['productModel'] || '',
                        productDesc: r['产品简介'] || r['产品描述'] || r['productDesc'] || '',
                        tags: [...new Set([...legacyTags, ...tags])],
                        tagsProvided,
                    };
                });
                const options = {
                    emptyTagAction: 'preserve',
                    overwriteEmpty: false,
                    duplicateModelAction: 'ask',
                    existingModelAction: 'ask',
                };
                const issueText = issues => (issues || []).slice(0, 20).map(item => `- ${item.message}`).join('\n');
                let preflight;
                for (let attempt = 0; attempt < 4; attempt += 1) {
                    const preflightResponse = await apiFetch('/api/admin/import/preflight', {
                        method: 'POST', body: JSON.stringify({ rows: mapped, options })
                    });
                    preflight = preflightResponse.data;
                    const fileDuplicates = (preflight.decisions || [])
                        .find(item => item.code === 'file_duplicate_models');
                    if (fileDuplicates) {
                        const overwrite = confirm(
                            `文件内发现${fileDuplicates.duplicateModelCount || 0}个重复型号。\n\n` +
                            '确定：采用同一型号最后出现的一行覆盖前面的行。\n' +
                            '取消：跳过这些重复型号的所有行。\n\n' +
                            '无论选择哪项，其他合格行都会继续导入。'
                        );
                        options.duplicateModelAction = overwrite ? 'last_wins' : 'skip';
                        continue;
                    }
                    const existingModels = (preflight.decisions || [])
                        .find(item => item.code === 'existing_models');
                    if (existingModels) {
                        const overwrite = confirm(
                            `数据库中已有${existingModels.existingModelCount || 0}个相同产品型号。\n\n` +
                            '确定：以表格的非空内容更新现有产品。\n' +
                            '取消：跳过已存在型号。\n\n' +
                            '无论选择哪项，其他合格行都会继续导入。'
                        );
                        options.existingModelAction = overwrite ? 'update' : 'skip';
                        continue;
                    }
                    break;
                }
                if (!preflight) throw new Error('导入预检没有返回结果');
                const summary = preflight.summary || {};
                if (!preflight.valid) {
                    alert(`没有可导入的合格行，未写入任何数据。\n\n${issueText(preflight.errors)}`);
                    return;
                }
                let confirmation = `预检完成，共${summary.total || 0}行：` +
                    `\n可导入 ${summary.validRows || 0}` +
                    `\n新建 ${summary.wouldCreate || 0}` +
                    `\n更新 ${summary.wouldUpdate || 0}` +
                    `\n无变化 ${summary.noChange || 0}` +
                    `\n校验失败并跳过 ${summary.invalidRows || 0}` +
                    `\n按重复规则跳过 ${summary.skippedRows || 0}`;
                if ((preflight.errors || []).length) {
                    confirmation += `\n\n失败行（其余合格行仍会导入）：\n${issueText(preflight.errors)}`;
                }
                if ((preflight.warnings || []).length) {
                    confirmation += `\n\n警告：\n${issueText(preflight.warnings)}`;
                }
                confirmation += '\n\n空白英文名/描述不会覆盖已有值；空白标签不会清空已有标签。确认提交？';
                if (!confirm(confirmation)) return;
                const result = await apiFetch('/api/admin/import', {
                    method: 'POST',
                    body: JSON.stringify({
                        rows: mapped, options, planHash: preflight.planHash,
                        confirmWarnings: (preflight.warnings || []).length > 0,
                    })
                });
                const d = result.data;
                const resultText = '导入完成: 新建' + (d.created||0) + '条, 更新' +
                    (d.updated||0) + '条, 无变化' + (d.unchanged||0) + '条, 校验失败跳过' +
                    (d.invalidRows||0) + '行, 重复规则跳过' + (d.skippedRows||0) + '行';
                showToast(resultText);
                if ((d.errors || []).length || (d.skipped || []).length) {
                    alert(`${resultText}\n\n失败/跳过明细：\n${issueText([...(d.errors || []), ...(d.skipped || [])])}`);
                }
                navigate('products');
            } catch(err) { showToast('导入失败: ' + err.message, 'error'); }
            finally { input.value = ''; }
        };
        reader.readAsArrayBuffer(input.files[0]);
    } catch(e) { showToast(e.message, 'error'); }
}

// ==================== 初始化 ====================
document.getElementById('login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const u = document.getElementById('login-username').value;
    const p = document.getElementById('login-password').value;
    const errEl = document.getElementById('login-error');
    try {
        await login(u, p);
    } catch(err) {
        errEl.textContent = err.message;
        errEl.style.display = 'block';
    }
});

document.getElementById('btn-logout').addEventListener('click', logout);

// 导航点击
document.querySelectorAll('.sidebar-nav a').forEach(a => {
    a.addEventListener('click', e => { e.preventDefault(); navigate(a.dataset.nav); });
});

// 启动：HttpOnly Cookie 不可由脚本读取，直接向服务端验证会话。
(async function init() {
    showLogin(false);
    showApp(false);
    try {
        const verifyData = await apiFetch('/api/admin/verify');
        STATE.admin = verifyData.data;
        document.getElementById('topbar-user').textContent = STATE.admin.username || '';
        showApp(true);
        navigate(location.hash.slice(1) || '');
    } catch (_) {
        clearSession();
    }
})();
