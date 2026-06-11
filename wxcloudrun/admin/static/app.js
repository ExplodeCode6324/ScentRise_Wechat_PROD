/**
 * ScentRise 后管 SPA — 路由 + API 客户端 + 页面渲染
 */

// ==================== 全局状态 ====================
const STATE = {
    token: localStorage.getItem('admin_token') || null,
    admin: JSON.parse(localStorage.getItem('admin_user') || 'null'),
    currentPage: ''
};

// ==================== API 客户端 ====================
const BASE = '';

async function apiFetch(url, options = {}) {
    const headers = { ...options.headers };
    if (STATE.token) {
        headers['Authorization'] = 'Bearer ' + STATE.token;
    }
    // 非 FormData 请求默认 JSON
    if (!(options.body instanceof FormData)) {
        headers['Content-Type'] = 'application/json';
    }
    const resp = await fetch(BASE + url, { ...options, headers });
    const data = await resp.json();
    if (resp.status === 401) {
        logout();
        throw new Error('登录已过期');
    }
    // 后端返回 {code: 0, data: ...} 或 {code: -1, errorMsg: ...}
    if (data.code !== undefined && data.code !== 0) {
        throw new Error(data.errorMsg || '请求失败');
    }
    return data;
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

// ==================== Quill 编辑器 ====================
function initQuill() {
    if (!window.Quill || !document.getElementById('editor')) return;
    // 上一次的 Quill 实例可能已脱离 DOM（页面切换后），重新创建
    if (window._quill) window._quill = null;
    window._quill = new Quill('#editor', {
        theme: 'snow',
        modules: { toolbar: [['bold','italic','underline'], ['link','image'], ['clean']] }
    });
}

// ==================== 登录/登出 ====================
async function login(username, password) {
    const data = await apiFetch('/api/admin/login', {
        method: 'POST',
        body: JSON.stringify({ username, password })
    });
    STATE.token = data.data.token;
    STATE.admin = data.data.admin;
    localStorage.setItem('admin_token', STATE.token);
    localStorage.setItem('admin_user', JSON.stringify(STATE.admin));
    showLogin(false);
    showApp(true);
    navigate(''); // Dashboard
}

function logout() {
    STATE.token = null;
    STATE.admin = null;
    localStorage.removeItem('admin_token');
    localStorage.removeItem('admin_user');
    showApp(false);
    showLogin(true);
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
    catch(e) { document.getElementById('app-content').innerHTML = '<div class="card"><p style="color:red">加载失败: '+e.message+'</p></div>'; }
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
                document.getElementById('app-content').innerHTML = '<div class="card"><p style="color:red">加载失败: ' + e.message + '</p></div>';
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
                    if (type === 'articles') setTimeout(initQuill, 100);
                }).catch(e => {
                    document.getElementById('app-content').innerHTML = '<div class="card"><p style="color:red">加载失败: ' + e.message + '</p></div>';
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
        if (hash.startsWith('articles/')) setTimeout(initQuill, 100);
    }).catch(e => {
        document.getElementById('app-content').innerHTML = '<div class="card"><p style="color:red">加载失败: ' + e.message + '</p></div>';
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
    if (STATE.token) navigate(hash);
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
            <div class="stat-card"><div class="stat-num">${(collectionsData.data || []).length}</div><div class="stat-label">合集数</div></div>
            <div class="stat-card"><div class="stat-num">${(tagsData.data || []).length}</div><div class="stat-label">标签数</div></div>
        </div>
        <div class="card">
            <div class="card-title">最近文章</div>
            ${(articlesData.data.list || []).map(a => `<div style="padding:6px 0;border-bottom:1px solid #eee;font-size:13px">${a.title}</div>`).join('') || '<p style="color:#999">暂无文章</p>'}
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
            <td>${p.productImage ? `<img src="${p.productImage}" class="img-thumb">` : '-'}</td>
            <td>${p.productModel || '-'}</td>
            <td>${p.productName || '-'}</td>
            <td>${p.productSeries || '-'}</td>
            <td>${(p.tags || []).map(t => {
                const cls = t.category === '产品系列' ? 'badge badge-primary' : 'badge badge-secondary';
                return `<span class="${cls}">${t.name}</span>`;
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
            <input type="text" id="search-input" placeholder="搜索产品名称/型号..." value="${_prodKeyword||''}"
                style="width:200px;padding:6px 10px;border:1px solid #ddd;border-radius:4px;margin-bottom:12px"
                oninput="searchProducts()">
            <table><thead><tr>
                <th>缩略图</th><th>型号</th><th>产品名</th><th>系列</th><th>标签</th><th>状态</th><th>操作</th>
            </tr></thead><tbody>${rows}</tbody></table>
            ${renderPagination(data.data.total, data.data.page, data.data.pageSize, 'goProductsPage')}
        </div>`;
}

async function renderProductForm(id) {
    const isEdit = !!id;
    let p = { productSeries:'', productModel:'', productName:'', productDesc:'', isActive:true, sortOrder:0, categoryId:'', tags:[], images:[] };
    if (isEdit) {
        const data = await apiFetch('/api/admin/products/' + id);
        p = data.data;
    }
    const [cats, tags, cols] = await Promise.all([
        apiFetch('/api/categories'),
        apiFetch('/api/tags'),
        apiFetch('/api/collections'),
    ]);
    const catOpts = (cats.data||[]).map(c => `<option value="${c.id}" ${p.categoryId==c.id?'selected':''}>${c.name}</option>`).join('');
    const seriesTags = (tags.data||[]).filter(t => t.category === '产品系列');
    const appTags = (tags.data||[]).filter(t => t.category !== '产品系列');
    const colOpts = (cols.data||[]).map(c => `<option value="${c.id}">${c.name}</option>`).join('');
    const selectedTagIds = (p.tags||[]).map(t=>t.id);
    const seriesCheckboxes = seriesTags.map(t => {
        const checked = selectedTagIds.includes(t.id) ? 'checked' : '';
        return `<label class="tag-checkbox"><input type="checkbox" name="tagIds" value="${t.id}" ${checked}> ${t.name}</label>`;
    }).join('');
    const appCheckboxes = appTags.map(t => {
        const checked = selectedTagIds.includes(t.id) ? 'checked' : '';
        return `<label class="tag-checkbox"><input type="checkbox" name="tagIds" value="${t.id}" ${checked}> ${t.name}</label>`;
    }).join('');
    const imagePreviews = (p.images||[]).map(img => `
        <div class="image-item">
            <img src="${img.imageUrl}" class="${img.isPrimary?'primary':''}">
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
                <div class="form-group"><label>产品型号 *</label><input name="productModel" value="${p.productModel||''}" ${isEdit?'readonly':''} required></div>
                <div class="form-group"><label>产品名称 *</label><input name="productName" value="${p.productName||''}" required></div>
                <div class="form-group"><label>产品描述</label><textarea name="productDesc">${p.productDesc||''}</textarea></div>
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
            <td>${t.icon ? `<img src="${t.icon}" class="img-thumb">` : '-'}</td>
            <td>${t.name}</td>
            <td>${t.category||'-'}</td>
            <td>${t.bannerImage ? `<img src="${t.bannerImage}" style="width:80px;height:30px;object-fit:cover;border-radius:2px">` : '-'}</td>
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
                <div class="form-group"><label>名称 *</label><input name="name" value="${t.name||''}" required></div>
                <div class="form-group"><label>分类</label><select name="category">
                    ${['产品系列','适用产品'].map(c=>`<option ${t.category==c?'selected':''}>${c}</option>`).join('')}
                </select></div>
                <div class="form-group"><label>排序</label><input name="sortOrder" type="number" value="${t.sortOrder||0}"></div>
                <button type="submit" class="btn btn-primary">保存</button>
            </form>
            ${isEdit ? `
            <div style="margin-top:16px">
                <div style="margin-bottom:8px"><strong>图标</strong> ${t.icon?`<img src="${t.icon}" style="width:30px;height:30px;vertical-align:middle;margin-left:8px">`:''}</div>
                <input type="file" id="tag-icon-file" accept="image/*"> <button class="btn btn-sm btn-primary" onclick="uploadTagImage(${id},'icon')">上传图标</button>
                <div style="margin-top:12px"><strong>横幅</strong> ${t.bannerImage?`<img src="${t.bannerImage}" style="width:120px;height:40px;vertical-align:middle;margin-left:8px;object-fit:cover">`:''}</div>
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
            <td>${c.coverImage?`<img src="${c.coverImage}" class="img-thumb">`:'-'}</td>
            <td>${c.name}</td>
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
                <div class="form-group"><label>名称 *</label><input name="name" value="${c.name||''}" required></div>
                <div class="form-group"><label>描述</label><textarea name="description">${c.description||''}</textarea></div>
                <div class="form-group"><label><input type="checkbox" name="isCarousel" ${c.isCarousel?'checked':''}> 首页轮播</label></div>
                <div class="form-group"><label>轮播排序</label><input name="carouselSort" type="number" value="${c.carouselSort||0}"></div>
                <div class="form-group"><label>排序</label><input name="sortOrder" type="number" value="${c.sortOrder||0}"></div>
                <button type="submit" class="btn btn-primary">保存</button>
            </form>
            ${isEdit ? `
            <div style="margin-top:12px"><strong>封面</strong> ${c.coverImage?`<img src="${c.coverImage}" class="img-preview">`:''}
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
            <span class="cp-info"><strong>${p.productName||'-'}</strong> <small>${p.productModel||''}</small></span>
            <span class="cp-series">${p.productSeries||''}</span>
        </label>`;
    }).join('');

    const rightRows = linked.map((p, i) => `
        <div class="cp-linked-item" data-pid="${p.id}">
            <span class="cp-order">${i+1}</span>
            <span class="cp-info"><strong>${p.productName||'-'}</strong> <small>${p.productModel||''}</small></span>
            <button class="btn btn-sm" onclick="removeLinkedProduct(this, ${p.id})" title="移除">×</button>
        </div>`).join('') || '<p style="color:#999;padding:12px">暂未关联产品</p>';

    return `
        <div class="page-header">
            <h2>合集产品管理：${col.name}</h2>
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
            <td>${a.coverImage?`<img src="${a.coverImage}" class="img-thumb">`:'-'}</td>
            <td><a href="javascript:navigate('articles/${a.id}')">${a.title}</a></td>
            <td>${a.author||'-'}</td>
            <td><span class="badge ${a.isPublished?'badge-success':'badge-warning'}">${a.isPublished?'已发布':'草稿'}</span></td>
            <td>${a.publishedAt||'-'}</td>
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
                <div class="form-group"><label>标题 *</label><input name="title" value="${a.title||''}" required></div>
                <div class="form-group"><label>作者</label><input name="author" value="${a.author||''}"></div>
                <div class="form-group"><label>正文 *</label>
                    <div id="editor-container" class="editor-container"><div id="editor">${a.content||''}</div></div>
                </div>
                <input type="hidden" name="content" id="content-hidden">
                <div class="form-group"><label>排序</label><input name="sortOrder" type="number" value="${a.sortOrder||0}"></div>
                <div class="form-group"><label><input type="radio" name="isPublished" value="1" ${a.isPublished?'checked':''}> 发布</label>
                <label style="margin-left:16px"><input type="radio" name="isPublished" value="0" ${!a.isPublished?'checked':''}> 草稿</label></div>
                <button type="submit" class="btn btn-primary">保存</button>
            </form>
            ${isEdit ? `
            <div style="margin-top:12px"><strong>封面</strong> ${a.coverImage?`<img src="${a.coverImage}" class="img-preview">`:''}
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
                <div class="form-group"><label>公司名称</label><input name="name" value="${c.name||''}"></div>
                <div class="form-group"><label>公司简介</label><textarea name="intro">${c.intro||''}</textarea></div>
                <div class="form-group"><label>联系电话</label><input name="phone" value="${c.phone||''}"></div>
                <div class="form-group"><label>微信号</label><input name="wechatId" value="${c.wechatId||''}"></div>
                <div class="form-group"><label>邮箱</label><input name="email" type="email" value="${c.email||''}"></div>
                <div class="form-group"><label>地址</label><input name="address" value="${c.address||''}"></div>
                <div class="form-group"><label>营业时间</label><input name="businessHours" value="${c.businessHours||''}"></div>
                <button type="submit" class="btn btn-primary">保存</button>
            </form>
            <div style="margin-top:12px"><strong>Logo</strong> ${c.logo?`<img src="${c.logo}" class="img-preview">`:''}
            <div><input type="file" id="company-logo-file" accept="image/*"> <button class="btn btn-sm btn-primary" onclick="uploadCompanyLogo()">上传 Logo</button></div></div>
            <div style="margin-top:12px"><strong>微信二维码</strong> ${c.wechatQr?`<img src="${c.wechatQr}" class="img-preview">`:''}
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
    const content = window._quill ? window._quill.root.innerHTML : '';
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
    try {
        // 使用 SheetJS 解析 Excel（需在 HTML 中引入 CDN）
        const reader = new FileReader();
        reader.onload = async function(e) {
            try {
                const data = new Uint8Array(e.target.result);
                const workbook = XLSX.read(data, {type: 'array'});
                const sheet = workbook.Sheets[workbook.SheetNames[0]];
                const rows = XLSX.utils.sheet_to_json(sheet);
                // Excel 列名映射（兼容「产品简介」和「产品描述」两种表头）
                // 标签列：E-K列独立检测 √ → 自动加入 tags 数组
                const TAG_COLUMNS = ['烘培', '糖果', '饮料', '炒货', '乳品', '膨化', '电子烟'];
                const mapped = rows.map(r => {
                    const tags = [];
                    // 检测 √ 标记的标签列
                    TAG_COLUMNS.forEach(col => {
                        const val = r[col];
                        if (val === '√' || val === 'v' || val === 'V' || val === 1 || val === '1' || val === true) {
                            tags.push(col);
                        }
                        // 也支持逗号分隔的「标签」列（兼容旧格式）
                    });
                    const legacyTags = (r['标签'] || r['tags'] || '').toString().split(/[,，;；]/).map(t => t.trim()).filter(Boolean);
                    return {
                        productSeries: r['产品系列'] || r['productSeries'] || '',
                        productName: r['产品名称'] || r['productName'] || '',
                        productModel: r['产品型号'] || r['productModel'] || '',
                        productDesc: r['产品简介'] || r['产品描述'] || r['productDesc'] || '',
                        tags: [...new Set([...legacyTags, ...tags])],  // 合并去重
                    };
                });
                const result = await apiFetch('/api/admin/import', { method: 'POST', body: JSON.stringify({ rows: mapped }) });
                const d = result.data;
                showToast('导入完成: 新建' + (d.created||0) + '条, 更新' + (d.updated||0) + '条');
                if (d.errors && d.errors.length > 0) {
                    alert('部分行导入失败:\n' + d.errors.join('\n'));
                }
                navigate('products');
            } catch(err) { showToast('导入失败: ' + err.message, 'error'); }
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

// 启动：先验证 token 有效性再决定显示哪个页面
(async function init() {
    if (STATE.token) {
        // 显示加载状态（防止闪烁）
        showLogin(false);
        showApp(false);
        try {
            const verifyData = await apiFetch('/api/admin/verify');
            // token 有效，显示管理页面
            STATE.admin = verifyData.data || verifyData;
            localStorage.setItem('admin_user', JSON.stringify(STATE.admin));
            document.getElementById('topbar-user').textContent = STATE.admin.username || '';
            showApp(true);
            navigate(location.hash.slice(1) || '');
        } catch (e) {
            // token 无效或已过期，清除并显示登录页
            console.warn('Token 验证失败:', e.message);
            STATE.token = null;
            STATE.admin = null;
            localStorage.removeItem('admin_token');
            localStorage.removeItem('admin_user');
            showLogin(true);
        }
    } else {
        showLogin(true);
    }
})();
