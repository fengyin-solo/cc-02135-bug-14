// 从配置文件获取API地址
const API_BASE = CONFIG.API_BASE;

let currentShareFileId = null;
let currentShareLink = null;
let myShares = [];
let selectedShareIds = new Set();
let shareFilter = 'all';
let shareLoadSerial = 0;

// Token 管理
const TokenManager = {
    TOKEN_KEY: 'auth_token',
    USER_KEY: 'auth_user',
    
    save(token, username) {
        localStorage.setItem(this.TOKEN_KEY, token);
        localStorage.setItem(this.USER_KEY, username);
    },
    
    get() {
        return localStorage.getItem(this.TOKEN_KEY);
    },
    
    getUser() {
        return localStorage.getItem(this.USER_KEY);
    },
    
    clear() {
        localStorage.removeItem(this.TOKEN_KEY);
        localStorage.removeItem(this.USER_KEY);
    },
    
    async isValid() {
        const token = this.get();
        if (!token) return false;
        
        try {
            const response = await fetch(`${API_BASE}/refresh-token?token=${token}`, {
                method: 'POST'
            });
            return response.ok;
        } catch {
            return false;
        }
    }
};

// 更新用户状态栏
async function updateUserBar() {
    const userBar = document.getElementById('userBar');
    const currentUser = document.getElementById('currentUser');
    const userAvatar = document.getElementById('userAvatar');
    const user = TokenManager.getUser();
    
    if (user && TokenManager.get() && await TokenManager.isValid()) {
        currentUser.textContent = user;
        userAvatar.textContent = user.charAt(0).toUpperCase();
        userBar.classList.remove('hidden');
        loadMyShares();
    } else {
        userBar.classList.add('hidden');
        const shareSection = document.getElementById('mySharesSection');
        if (shareSection) {
            shareSection.style.display = 'none';
            myShares = [];
            selectedShareIds.clear();
            hideBatchResult();
        }
    }
}

// 退出登录
function logout() {
    TokenManager.clear();
    updateUserBar();
}

// 页面加载时获取文件列表和更新用户状态
document.addEventListener('DOMContentLoaded', async () => {
    // 检查token是否有效，无效则清除
    if (TokenManager.get() && !(await TokenManager.isValid())) {
        TokenManager.clear();
    }
    await updateUserBar();
    loadFileList();
});

// 验证文件
function validateFile(file) {
    if (file.size > CONFIG.MAX_FILE_SIZE) {
        return `文件大小超过限制（最大${CONFIG.MAX_FILE_SIZE / 1024 / 1024}MB）`;
    }
    return null;
}

// 上传文件处理函数
async function uploadFile(file) {
    const validationError = validateFile(file);
    if (validationError) {
        document.getElementById('uploadStatus').textContent = `❌ ${validationError}`;
        return;
    }

    showLoading('上传中...');
    
    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch(`${API_BASE}/upload`, {
            method: 'POST',
            body: formData
        });
        const result = await response.json();
        
        if (response.ok) {
            document.getElementById('uploadStatus').textContent = `✅ ${file.name} 上传成功！`;
            loadFileList();
        } else {
            document.getElementById('uploadStatus').textContent = `❌ 上传失败: ${result.error}`;
        }
    } catch (error) {
        document.getElementById('uploadStatus').textContent = `❌ 上传失败: ${error.message}`;
    } finally {
        hideLoading();
    }
}

// 文件选择上传
document.getElementById('fileInput').addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    await uploadFile(file);
    e.target.value = '';
});

// 拖拽上传
const uploadZone = document.querySelector('.upload-zone');

uploadZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    uploadZone.classList.add('drag-over');
});

uploadZone.addEventListener('dragleave', (e) => {
    e.preventDefault();
    uploadZone.classList.remove('drag-over');
});

uploadZone.addEventListener('drop', async (e) => {
    e.preventDefault();
    uploadZone.classList.remove('drag-over');
    
    const file = e.dataTransfer.files[0];
    if (file) {
        await uploadFile(file);
    }
});

// 加载文件列表
async function loadFileList() {
    showLoading('加载文件列表...');
    
    try {
        const response = await fetch(`${API_BASE}/files`);
        const files = await response.json();
        
        const fileList = document.getElementById('fileList');
        const isLoggedIn = TokenManager.get() && (await TokenManager.isValid());
        
        if (files.length === 0) {
            fileList.innerHTML = '<p class="empty-msg">暂无可下载文件</p>';
        } else {
            fileList.innerHTML = files.map(file => `
                <div class="file-item">
                    <div class="file-info">
                        <div class="file-icon">${getFileIcon(file.name)}</div>
                        <div class="file-details">
                            <div class="file-name">${escapeHtml(file.name)}</div>
                            <div class="file-size">${formatSize(file.size)}</div>
                        </div>
                    </div>
                    <div class="file-actions">
                        ${isLoggedIn ? `<button class="share-btn" onclick="openShareModal('${escapeHtml(file.id)}', '${escapeHtml(file.name)}')">分享</button>` : ''}
                        <button class="download-btn" onclick="requestDownload('${escapeHtml(file.id)}')">
                            下载
                        </button>
                    </div>
                </div>
            `).join('');
        }
    } catch (error) {
        document.getElementById('fileList').innerHTML = 
            `<p class="empty-msg">加载失败: ${escapeHtml(error.message)}</p>`;
    } finally {
        hideLoading();
    }
}

// HTML转义防止XSS
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// 请求下载 - 检查token是否有效，有效则直接下载
async function requestDownload(fileId) {
    showLoading('检查授权...');
    
    // 检查是否有有效的token
    if (await TokenManager.isValid()) {
        // token有效，使用 fetch + Authorization 头下载
        document.getElementById('loadingText').textContent = '正在下载...';
        try {
            const response = await fetch(`${API_BASE}/download/${fileId}`, {
                method: 'GET',
                headers: {
                    'Authorization': `Bearer ${TokenManager.get()}`
                }
            });
            if (response.ok) {
                const blob = await response.blob();
                const contentDisposition = response.headers.get('Content-Disposition');
                let filename = 'download';
                if (contentDisposition) {
                    const match = contentDisposition.match(/filename\*?=(?:UTF-8'')?["']?([^"';\n]+)/i);
                    if (match) filename = decodeURIComponent(match[1]);
                }
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                a.remove();
            } else {
                const result = await response.json();
                alert(`下载失败: ${result.error || '未知错误'}`);
            }
        } catch (error) {
            alert(`下载失败: ${error.message}`);
        } finally {
            hideLoading();
        }
        return;
    }
    
    // token无效或不存在，弹出登录框
    hideLoading();
    TokenManager.clear();
    document.getElementById('downloadFileId').value = fileId;
    document.getElementById('authModal').classList.add('active');
    document.getElementById('authError').textContent = '';
    document.getElementById('username').value = '';
    document.getElementById('password').value = '';
    document.getElementById('username').focus();
}

// 关闭验证弹窗
function closeAuthModal() {
    document.getElementById('authModal').classList.remove('active');
}

// 身份验证表单提交
document.getElementById('authForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const username = document.getElementById('username').value.trim();
    const password = document.getElementById('password').value;
    const fileId = document.getElementById('downloadFileId').value;

    if (!username || !password) {
        document.getElementById('authError').textContent = '请输入用户名和密码';
        return;
    }

    showLoading('验证身份...');
    
    try {
        const response = await fetch(`${API_BASE}/auth`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });
        
        const result = await response.json();
        
        if (response.ok && result.success) {
            // 保存token和用户名到本地
            TokenManager.save(result.token, username);
            await updateUserBar();
            loadFileList();
            
            closeAuthModal();
            document.getElementById('loadingText').textContent = '验证成功，正在下载...';
            
            // 使用 fetch + Authorization 头下载
            try {
                const downloadResponse = await fetch(`${API_BASE}/download/${fileId}`, {
                    method: 'GET',
                    headers: {
                        'Authorization': `Bearer ${result.token}`
                    }
                });
                if (downloadResponse.ok) {
                    const blob = await downloadResponse.blob();
                    const contentDisposition = downloadResponse.headers.get('Content-Disposition');
                    let filename = 'download';
                    if (contentDisposition) {
                        const match = contentDisposition.match(/filename\*?=(?:UTF-8'')?["']?([^"';\n]+)/i);
                        if (match) filename = decodeURIComponent(match[1]);
                    }
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = filename;
                    document.body.appendChild(a);
                    a.click();
                    window.URL.revokeObjectURL(url);
                    a.remove();
                } else {
                    const errResult = await downloadResponse.json();
                    document.getElementById('authError').textContent = `下载失败: ${errResult.error || '未知错误'}`;
                }
            } catch (downloadError) {
                document.getElementById('authError').textContent = `下载失败: ${downloadError.message}`;
            } finally {
                hideLoading();
            }
        } else if (response.status === 429) {
            hideLoading();
            document.getElementById('authError').textContent = '请求过于频繁，请稍后再试';
        } else {
            hideLoading();
            document.getElementById('authError').textContent = result.error || '验证失败，请检查账号密码';
        }
    } catch (error) {
        hideLoading();
        document.getElementById('authError').textContent = `验证失败: ${error.message}`;
    }
});

// 显示加载动画
function showLoading(text = '加载中...') {
    document.getElementById('loadingText').textContent = text;
    document.getElementById('loadingOverlay').classList.add('active');
}

// 隐藏加载动画
function hideLoading() {
    document.getElementById('loadingOverlay').classList.remove('active');
}

// 获取文件图标
function getFileIcon(filename) {
    const ext = filename.split('.').pop().toLowerCase();
    const icons = {
        pdf: '📄', doc: '📝', docx: '📝', txt: '📃',
        jpg: '🖼️', jpeg: '🖼️', png: '🖼️', gif: '🖼️',
        mp3: '🎵', wav: '🎵', mp4: '🎬', avi: '🎬',
        zip: '📦', rar: '📦', '7z': '📦',
        js: '💻', py: '🐍', html: '🌐', css: '🎨'
    };
    return icons[ext] || '📁';
}

// 格式化文件大小
function formatSize(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// 格式化时间戳
function formatTimestamp(timestamp) {
    if (!timestamp) return '永久有效';
    const date = new Date(timestamp * 1000);
    return date.toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
    });
}

// 格式化剩余时间
function formatRemainingTime(expiresAt) {
    if (!expiresAt) return '永久';
    const remaining = expiresAt - (Date.now() / 1000);
    if (remaining <= 0) return '已过期';
    
    const hours = Math.floor(remaining / 3600);
    const minutes = Math.floor((remaining % 3600) / 60);
    
    if (hours > 24) {
        const days = Math.floor(hours / 24);
        return `${days} 天 ${hours % 24} 小时`;
    } else if (hours > 0) {
        return `${hours} 小时 ${minutes} 分钟`;
    } else {
        return `${minutes} 分钟`;
    }
}

// 打开分享设置弹窗
function openShareModal(fileId, fileName) {
    currentShareFileId = fileId;
    document.getElementById('shareFileName').textContent = fileName;
    document.getElementById('shareError').textContent = '';
    document.getElementById('expireHours').value = '24';
    document.getElementById('maxDownloads').value = '10';
    document.getElementById('shareModal').classList.add('active');
}

// 关闭分享设置弹窗
function closeShareModal() {
    document.getElementById('shareModal').classList.remove('active');
    currentShareFileId = null;
}

// 确认创建分享链接
async function confirmCreateShare() {
    if (!currentShareFileId) return;
    
    const expireHours = parseInt(document.getElementById('expireHours').value);
    const maxDownloads = parseInt(document.getElementById('maxDownloads').value);
    
    showLoading('生成分享链接...');
    document.getElementById('shareError').textContent = '';
    
    try {
        const response = await fetch(`${API_BASE}/share`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${TokenManager.get()}`
            },
            body: JSON.stringify({
                file_id: currentShareFileId,
                expire_hours: expireHours,
                max_downloads: maxDownloads
            })
        });
        
        const result = await response.json();
        
        if (response.ok && result.success) {
            closeShareModal();
            showShareSuccessModal(result);
            loadMyShares();
        } else {
            document.getElementById('shareError').textContent = result.error || '生成分享链接失败';
        }
    } catch (error) {
        document.getElementById('shareError').textContent = `错误: ${error.message}`;
    } finally {
        hideLoading();
    }
}

// 显示分享成功弹窗
function showShareSuccessModal(result) {
    currentShareLink = `${window.location.origin}/share.html#${result.share_id}`;
    
    document.getElementById('shareLinkInput').value = currentShareLink;
    document.getElementById('shareInfoName').textContent = result.filename;
    document.getElementById('shareInfoExpire').textContent = formatTimestamp(result.expires_at);
    document.getElementById('shareInfoDownloads').textContent = result.max_downloads ? `${result.max_downloads} 次` : '无限制';
    document.getElementById('copyBtnText').textContent = '复制';
    
    const copyBtn = document.querySelector('.copy-btn');
    copyBtn.classList.remove('copied');
    
    document.getElementById('shareSuccessModal').classList.add('active');
}

// 关闭分享成功弹窗
function closeShareSuccessModal() {
    document.getElementById('shareSuccessModal').classList.remove('active');
    currentShareLink = null;
}

// 复制分享链接
async function copyShareLink() {
    const linkInput = document.getElementById('shareLinkInput');
    const copyBtnText = document.getElementById('copyBtnText');
    const copyBtn = document.querySelector('.copy-btn');
    
    try {
        await navigator.clipboard.writeText(linkInput.value);
        copyBtnText.textContent = '已复制';
        copyBtn.classList.add('copied');
        
        setTimeout(() => {
            copyBtnText.textContent = '复制';
            copyBtn.classList.remove('copied');
        }, 2000);
    } catch (error) {
        linkInput.select();
        document.execCommand('copy');
        copyBtnText.textContent = '已复制';
        copyBtn.classList.add('copied');
        
        setTimeout(() => {
            copyBtnText.textContent = '复制';
            copyBtn.classList.remove('copied');
        }, 2000);
    }
}

// 加载我的分享列表
async function loadMyShares() {
    const section = document.getElementById('mySharesSection');
    const list = document.getElementById('mySharesList');

    if (!(await TokenManager.isValid())) {
        section.style.display = 'none';
        return;
    }

    section.style.display = 'block';
    const requestSerial = ++shareLoadSerial;

    try {
        const response = await fetch(`${API_BASE}/shares`, {
            headers: {
                'Authorization': `Bearer ${TokenManager.get()}`
            }
        });

        if (!response.ok) {
            throw new Error((await response.json()).error || '加载失败');
        }

        const shares = await response.json();
        if (requestSerial !== shareLoadSerial) return;

        myShares = shares;
        selectedShareIds = new Set([...selectedShareIds].filter(id => myShares.some(share => share.share_id === id)));
        renderMyShares();
    } catch (error) {
        if (requestSerial === shareLoadSerial) {
            myShares = [];
            selectedShareIds.clear();
            list.innerHTML = `<p class="empty-msg">加载失败: ${escapeHtml(error.message)}</p>`;
            updateShareToolbar();
        }
    }
}

function getShareById(shareId) {
    return myShares.find(share => share.share_id === shareId);
}

function getVisibleShares() {
    if (shareFilter === 'active') {
        return myShares.filter(share => share.is_active);
    }
    if (shareFilter === 'disabled') {
        return myShares.filter(share => !share.is_active);
    }
    return myShares;
}

function getShareStatus(share) {
    if (!share.is_active) {
        return { className: 'invalid', text: '已停用' };
    }
    return {
        className: share.is_valid ? 'valid' : 'invalid',
        text: share.is_valid ? '有效' : (share.error_msg || '无效')
    };
}

function renderMyShares() {
    const list = document.getElementById('mySharesList');
    const visibleShares = getVisibleShares();

    if (myShares.length === 0) {
        list.innerHTML = '<p class="empty-msg">暂无分享链接</p>';
    } else if (visibleShares.length === 0) {
        list.innerHTML = '<p class="empty-msg">当前筛选条件下暂无分享链接</p>';
    } else {
        list.innerHTML = visibleShares.map(share => {
            const status = getShareStatus(share);
            const checked = selectedShareIds.has(share.share_id) ? 'checked' : '';
            const disabled = share.is_active ? '' : 'disabled';
            const copyClass = share.is_active ? 'copy-link-btn' : 'copy-link-btn disabled-btn';

            return `
                <div class="share-item ${share.is_active ? '' : 'share-item-disabled'}">
                    <label class="share-select">
                        <input type="checkbox" class="share-checkbox" data-share-id="${escapeHtml(share.share_id)}" ${checked}>
                    </label>
                    <div class="share-main">
                        <div class="share-item-header">
                            <span class="share-item-filename">${escapeHtml(share.filename)}</span>
                            <span class="share-item-status ${status.className}">${status.text}</span>
                        </div>
                        <div class="share-item-details">
                            <div class="share-item-detail">
                                <span class="share-item-detail-label">剩余时间</span>
                                <span class="share-item-detail-value">${formatRemainingTime(share.expires_at)}</span>
                            </div>
                            <div class="share-item-detail">
                                <span class="share-item-detail-label">已下载</span>
                                <span class="share-item-detail-value">${share.download_count} / ${share.max_downloads || '∞'}</span>
                            </div>
                            <div class="share-item-detail">
                                <span class="share-item-detail-label">创建时间</span>
                                <span class="share-item-detail-value">${new Date(share.created_at).toLocaleString('zh-CN')}</span>
                            </div>
                        </div>
                        <div class="share-item-actions">
                            <button class="${copyClass}" onclick="copyShareLinkFromList('${escapeHtml(share.share_id)}')" ${disabled}>
                                🔗 复制链接
                            </button>
                            <button class="restore-share-btn" onclick="restoreSingleShare('${escapeHtml(share.share_id)}')" ${share.is_active ? 'hidden' : ''}>
                                ↩️ 恢复
                            </button>
                            <button class="delete-share-btn" onclick="deleteShare('${escapeHtml(share.share_id)}')" ${share.is_active ? '' : 'disabled'}>
                                🗑️ 永久删除
                            </button>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    }

    updateShareToolbar();
}

function updateShareToolbar() {
    const activeShares = myShares.filter(share => share.is_active);
    const disabledShares = myShares.filter(share => !share.is_active);
    const visibleShares = getVisibleShares();
    const visibleIds = visibleShares.map(share => share.share_id);
    const visibleSelectedIds = visibleIds.filter(id => selectedShareIds.has(id));

    document.getElementById('shareCountAll').textContent = myShares.length;
    document.getElementById('shareCountActive').textContent = activeShares.length;
    document.getElementById('shareCountDisabled').textContent = disabledShares.length;

    const selectAll = document.getElementById('selectAllShares');
    selectAll.checked = visibleIds.length > 0 && visibleSelectedIds.length === visibleIds.length;
    selectAll.indeterminate = visibleSelectedIds.length > 0 && visibleSelectedIds.length < visibleIds.length;
    selectAll.disabled = visibleIds.length === 0;

    const selectedShares = myShares.filter(share => selectedShareIds.has(share.share_id));
    const hasActiveSelection = selectedShares.some(share => share.is_active);
    const hasDisabledSelection = selectedShares.some(share => !share.is_active);
    document.getElementById('batchDisableBtn').disabled = !hasActiveSelection;
    document.getElementById('batchRestoreBtn').disabled = !hasDisabledSelection;

    document.querySelectorAll('.share-filter-btn').forEach(button => {
        button.classList.toggle('active', button.dataset.filter === shareFilter);
    });
}

function toggleShareSelection(shareId, checked) {
    if (checked) {
        selectedShareIds.add(shareId);
    } else {
        selectedShareIds.delete(shareId);
    }
    updateShareToolbar();
}

function selectAllVisibleShares(checked) {
    const visibleIds = getVisibleShares().map(share => share.share_id);
    if (checked) {
        visibleIds.forEach(id => selectedShareIds.add(id));
    } else {
        visibleIds.forEach(id => selectedShareIds.delete(id));
    }
    renderMyShares();
}

function setShareFilter(filter) {
    shareFilter = filter;
    renderMyShares();
}

function hideBatchResult() {
    const resultBox = document.getElementById('shareBatchResult');
    if (resultBox) {
        resultBox.hidden = true;
        resultBox.textContent = '';
        resultBox.className = 'batch-result-msg';
    }
}

function showBatchResult(result) {
    const resultBox = document.getElementById('shareBatchResult');
    const failures = result.results.filter(item => !item.success);
    const failureText = failures.map(item => `${item.share_id}: ${item.message}`).join('；');
    const listText = `管理页当前共 ${myShares.length} 条分享记录`;

    if (failures.length > 0) {
        resultBox.textContent =
            `提交 ${result.total} 条，成功 ${result.success_count} 条，失败 ${result.failed_count} 条。${listText}。失败项：${failureText}`;
        resultBox.className = 'batch-result-msg partial';
    } else {
        resultBox.textContent =
            `提交 ${result.total} 条，成功 ${result.success_count} 条，失败 0 条。${listText}。`;
        resultBox.className = 'batch-result-msg success';
    }
    resultBox.hidden = false;
}

async function submitShareBatch(action) {
    const shareIds = [...selectedShareIds];
    if (shareIds.length === 0) return;

    const actionText = action === 'delete' ? '停用' : '恢复';
    if (!confirm(`确定要${actionText}选中的 ${shareIds.length} 条分享记录吗？`)) {
        return;
    }

    hideBatchResult();
    showLoading(`批量${actionText}中...`);
    let batchResult = null;

    try {
        const response = await fetch(`${API_BASE}/shares/batch`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${TokenManager.get()}`
            },
            body: JSON.stringify({ action, share_ids: shareIds })
        });

        batchResult = await response.json();
        if (!response.ok) {
            throw new Error(batchResult.error || `批量${actionText}失败`);
        }

        selectedShareIds = new Set(
            batchResult.results.filter(item => !item.success).map(item => item.share_id)
        );
    } catch (error) {
        const resultBox = document.getElementById('shareBatchResult');
        resultBox.textContent = `批量${actionText}失败: ${error.message}`;
        resultBox.className = 'batch-result-msg partial';
        resultBox.hidden = false;
    } finally {
        hideLoading();
        await loadMyShares();
        if (batchResult) {
            showBatchResult(batchResult);
        }
    }
}

// 从分享列表复制链接
async function copyShareLinkFromList(shareId) {
    const share = getShareById(shareId);
    if (!share || !share.is_active || !share.is_valid) {
        alert('该分享链接已停用或已失效，无法复制');
        return;
    }

    const link = `${window.location.origin}/share.html#${encodeURIComponent(share.share_id)}`;
    try {
        await navigator.clipboard.writeText(link);
        alert('分享链接已复制到剪贴板');
    } catch (error) {
        prompt('请手动复制链接:', link);
    }
}

async function restoreSingleShare(shareId) {
    const share = getShareById(shareId);
    if (!share || share.is_active) return;

    if (!confirm('确定要恢复此分享链接吗？恢复后有效链接将重新可访问。')) {
        return;
    }

    hideBatchResult();
    showLoading('恢复中...');
    try {
        const response = await fetch(`${API_BASE}/shares/batch`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${TokenManager.get()}`
            },
            body: JSON.stringify({ action: 'restore', share_ids: [shareId] })
        });
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.error || '恢复失败');
        }
        const item = result.results[0];
        if (!item.success) {
            alert(`恢复失败: ${item.message}`);
        }
    } catch (error) {
        alert(`恢复失败: ${error.message}`);
    } finally {
        hideLoading();
        await loadMyShares();
    }
}

// 永久删除单条分享链接
async function deleteShare(shareId) {
    const share = getShareById(shareId);
    if (!share || !share.is_active) {
        alert('已停用记录请先恢复后再永久删除');
        return;
    }

    if (!confirm('确定要永久删除此分享链接吗？删除后链接将立即失效且无法恢复。')) {
        return;
    }

    hideBatchResult();
    showLoading('删除中...');

    try {
        const response = await fetch(`${API_BASE}/share/${shareId}`, {
            method: 'DELETE',
            headers: {
                'Authorization': `Bearer ${TokenManager.get()}`
            }
        });

        if (response.ok) {
            selectedShareIds.delete(shareId);
            await loadMyShares();
        } else {
            const result = await response.json();
            alert(`删除失败: ${result.error || '未知错误'}`);
        }
    } catch (error) {
        alert(`删除失败: ${error.message}`);
    } finally {
        hideLoading();
    }
}

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('selectAllShares').addEventListener('change', event => {
        selectAllVisibleShares(event.target.checked);
    });

    document.getElementById('mySharesList').addEventListener('change', event => {
        if (event.target.classList.contains('share-checkbox')) {
            toggleShareSelection(event.target.dataset.shareId, event.target.checked);
        }
    });

    document.querySelectorAll('.share-filter-btn').forEach(button => {
        button.addEventListener('click', () => setShareFilter(button.dataset.filter));
    });

    document.getElementById('batchDisableBtn').addEventListener('click', () => submitShareBatch('delete'));
    document.getElementById('batchRestoreBtn').addEventListener('click', () => submitShareBatch('restore'));
});

