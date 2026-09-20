"""文件路由"""
import os
import re
import uuid
import time
import logging
from flask import request, jsonify, send_file
from routes import files_bp
from database import get_db
from auth import verify_token, get_username_from_token, login_required
from config import UPLOAD_FOLDER, MAX_FILE_SIZE, BLOCKED_EXTENSIONS, SHARE_LINK_EXPIRE_HOURS, SHARE_LINK_MAX_DOWNLOADS

logger = logging.getLogger(__name__)


def allowed_file(filename):
    """检查文件扩展名是否被禁止"""
    if '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    return ext not in BLOCKED_EXTENSIONS


@files_bp.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': '没有文件'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '未选择文件'}), 400

    if not allowed_file(file.filename):
        return jsonify({'error': '不支持的文件类型'}), 400

    file.seek(0, 2)
    file_size = file.tell()
    file.seek(0)

    if file_size > MAX_FILE_SIZE:
        return jsonify({'error': f'文件大小超过限制（最大{MAX_FILE_SIZE // 1024 // 1024}MB）'}), 400

    file_id = str(uuid.uuid4())
    # 保留原始文件名用于显示（去掉路径分隔符防止注入）
    original_name = re.sub(r'[/\\]', '_', file.filename).strip()
    if not original_name:
        original_name = file_id

    # 磁盘上用 UUID + 扩展名存储，避免文件名编码问题
    ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
    safe_filename = f"{file_id}.{ext}" if ext else file_id
    filepath = os.path.join(UPLOAD_FOLDER, safe_filename)
    file.save(filepath)

    file_size = os.path.getsize(filepath)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO files (id, name, path, size) VALUES (?, ?, ?, ?)',
        (file_id, original_name, filepath, file_size)
    )
    conn.commit()
    conn.close()

    logger.info(f"文件上传成功: {original_name} (ID: {file_id}, 大小: {file_size} bytes)")
    return jsonify({'success': True, 'file_id': file_id, 'filename': original_name})


@files_bp.route('/api/files', methods=['GET'])
def list_files():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT id, name, path, size FROM files')
    files = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(files)


@files_bp.route('/api/download/<file_id>', methods=['GET'])
def download_file(file_id):
    # 优先从 Authorization 头获取 token，兼容查询参数（已废弃）
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        token = auth_header[7:]
    else:
        token = request.args.get('token')  # 向后兼容，建议前端迁移到 Authorization 头

    if not token or not verify_token(token):
        return jsonify({'error': '未授权或token已过期'}), 401

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT name, path FROM files WHERE id = ?', (file_id,))
    file_info = cursor.fetchone()
    conn.close()

    if not file_info:
        return jsonify({'error': '文件不存在'}), 404

    if not os.path.abspath(file_info['path']).startswith(os.path.abspath(UPLOAD_FOLDER)):
        return jsonify({'error': '非法文件路径'}), 403

    if not os.path.exists(file_info['path']):
        return jsonify({'error': '文件不存在'}), 404

    logger.info(f"文件下载: {file_info['name']} (ID: {file_id})")
    return send_file(file_info['path'], as_attachment=True, download_name=file_info['name'])


def generate_short_id():
    """生成短的分享链接ID"""
    return uuid.uuid4().hex[:12]


def get_share_link_info(share_id):
    """获取分享链接信息，包含文件信息和有效性检查"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT s.id, s.file_id, s.created_by, s.expires_at, s.max_downloads,
               s.download_count, s.is_active, s.created_at,
               f.name as filename, f.size as filesize
        FROM share_links s
        JOIN files f ON s.file_id = f.id
        WHERE s.id = ?
    ''', (share_id,))
    share = cursor.fetchone()
    conn.close()
    return share


def is_share_valid(share):
    """检查分享链接是否有效"""
    if not share:
        return False, '分享链接不存在'

    if not share['is_active']:
        return False, '分享链接已停用'

    if share['expires_at'] is not None and share['expires_at'] < time.time():
        return False, '分享链接已过期'

    if share['max_downloads'] is not None and share['download_count'] >= share['max_downloads']:
        return False, '分享链接下载次数已用完'

    return True, None


def increment_download_count(share_id):
    """原子增加下载次数，避免停用或达到上限后仍继续下载"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE share_links
        SET download_count = download_count + 1
        WHERE id = ?
          AND is_active = 1
          AND (expires_at IS NULL OR expires_at > ?)
          AND (max_downloads IS NULL OR download_count < max_downloads)
    ''', (share_id, time.time()))
    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return updated


def get_token_from_request():
    """从请求中获取 token"""
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        return auth_header[7:]
    return request.args.get('token')


def serialize_share(share, include_state=False):
    """序列化分享记录，状态字段与数据库记录保持一致"""
    valid, error_msg = is_share_valid(share)
    data = {
        'share_id': share['id'],
        'file_id': share['file_id'],
        'filename': share['filename'],
        'filesize': share['filesize'],
        'created_by': share['created_by'],
        'expires_at': share['expires_at'],
        'max_downloads': share['max_downloads'],
        'download_count': share['download_count'],
        'created_at': share['created_at'],
        'is_valid': valid,
        'error_msg': error_msg
    }
    if include_state:
        data['is_active'] = bool(share['is_active'])
    return data


def normalize_share_ids(raw_ids):
    """校验并去重批量操作的分享 ID，保持调用方传入顺序"""
    if not isinstance(raw_ids, list) or not raw_ids:
        return None, 'share_ids 必须是非空数组'

    share_ids = []
    seen = set()
    for raw_id in raw_ids:
        if not isinstance(raw_id, str):
            return None, '分享ID必须是字符串'
        share_id = raw_id.strip()
        if not share_id:
            return None, '分享ID不能为空'
        if share_id not in seen:
            share_ids.append(share_id)
            seen.add(share_id)

    if len(share_ids) > 200:
        return None, '单次最多操作 200 条分享记录'
    return share_ids, None


@files_bp.route('/api/share', methods=['POST'])
@login_required
def create_share():
    """创建分享链接"""
    data = request.get_json()
    if not data:
        return jsonify({'error': '无效的请求数据'}), 400

    file_id = data.get('file_id', '').strip()
    expire_hours = data.get('expire_hours')
    max_downloads = data.get('max_downloads')

    if not file_id:
        return jsonify({'error': '文件ID不能为空'}), 400

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT id, name FROM files WHERE id = ?', (file_id,))
    file_info = cursor.fetchone()

    if not file_info:
        conn.close()
        return jsonify({'error': '文件不存在'}), 404

    if expire_hours is None:
        expire_hours = SHARE_LINK_EXPIRE_HOURS

    if expire_hours < 0:
        expire_hours = None

    if expire_hours is not None:
        expires_at = time.time() + expire_hours * 3600
    else:
        expires_at = None

    if max_downloads is None:
        max_downloads = SHARE_LINK_MAX_DOWNLOADS

    if max_downloads < 0:
        max_downloads = None

    token = get_token_from_request()
    username = get_username_from_token(token)

    share_id = generate_short_id()

    cursor.execute('''
        INSERT INTO share_links (id, file_id, created_by, expires_at, max_downloads, is_active)
        VALUES (?, ?, ?, ?, ?, 1)
    ''', (share_id, file_id, username, expires_at, max_downloads))

    conn.commit()
    conn.close()

    logger.info(f"分享链接创建成功: 文件 {file_info['name']}, 分享ID {share_id}, 创建者 {username}")

    return jsonify({
        'success': True,
        'share_id': share_id,
        'expires_at': expires_at,
        'max_downloads': max_downloads,
        'filename': file_info['name']
    })


@files_bp.route('/api/share/<share_id>', methods=['GET'])
def get_share(share_id):
    """获取分享链接信息（公开访问）"""
    share = get_share_link_info(share_id)

    if not share or not share['is_active']:
        return jsonify({'error': '分享链接不存在'}), 404

    valid, error_msg = is_share_valid(share)
    if not valid:
        return jsonify({'error': error_msg}), 404

    return jsonify(serialize_share(share))


@files_bp.route('/api/share/<share_id>/download', methods=['GET'])
def download_by_share(share_id):
    """通过分享链接下载文件（公开访问）"""
    share = get_share_link_info(share_id)
    valid, error_msg = is_share_valid(share)

    if not valid:
        return jsonify({'error': error_msg}), 404

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT name, path FROM files WHERE id = ?', (share['file_id'],))
    file_info = cursor.fetchone()
    conn.close()

    if not file_info:
        return jsonify({'error': '文件不存在'}), 404

    if not os.path.abspath(file_info['path']).startswith(os.path.abspath(UPLOAD_FOLDER)):
        return jsonify({'error': '非法文件路径'}), 403

    if not os.path.exists(file_info['path']):
        return jsonify({'error': '文件不存在'}), 404

    if not increment_download_count(share_id):
        return jsonify({'error': '分享链接不存在或已失效'}), 404

    logger.info(f"分享下载: 文件 {file_info['name']}, 分享ID {share_id}")
    return send_file(file_info['path'], as_attachment=True, download_name=file_info['name'])


@files_bp.route('/api/shares', methods=['GET'])
@login_required
def list_shares():
    """获取当前用户的所有分享链接，包括已停用待恢复的记录"""
    token = get_token_from_request()
    username = get_username_from_token(token)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT s.id, s.file_id, s.created_by, s.expires_at, s.max_downloads,
               s.download_count, s.is_active, s.created_at,
               f.name as filename, f.size as filesize
        FROM share_links s
        JOIN files f ON s.file_id = f.id
        WHERE s.created_by = ?
        ORDER BY s.created_at DESC
    ''', (username,))
    shares = cursor.fetchall()
    conn.close()

    return jsonify([serialize_share(share, include_state=True) for share in shares])


@files_bp.route('/api/shares/batch', methods=['POST'])
@login_required
def batch_update_shares():
    """批量停用或恢复当前用户的分享链接，逐条做归属校验并逐条返回结果"""
    data = request.get_json()
    if not data:
        return jsonify({'error': '无效的请求数据'}), 400

    action = data.get('action')
    if action not in ('delete', 'restore'):
        return jsonify({'error': "action 必须是 'delete' 或 'restore'"}), 400

    share_ids, error = normalize_share_ids(data.get('share_ids'))
    if error:
        return jsonify({'error': error}), 400

    token = get_token_from_request()
    username = get_username_from_token(token)
    target_active = 0 if action == 'delete' else 1
    results = []

    conn = get_db()
    cursor = conn.cursor()
    for share_id in share_ids:
        try:
            cursor.execute(
                'SELECT id, created_by, is_active FROM share_links WHERE id = ?',
                (share_id,)
            )
            share = cursor.fetchone()

            if not share:
                results.append({
                    'share_id': share_id,
                    'success': False,
                    'status': 404,
                    'message': '分享链接不存在'
                })
                continue

            if share['created_by'] != username:
                results.append({
                    'share_id': share_id,
                    'success': False,
                    'status': 403,
                    'message': '无权限操作此分享链接'
                })
                continue

            if share['is_active'] == target_active:
                message = '分享链接已停用' if action == 'delete' else '分享链接已恢复'
                results.append({
                    'share_id': share_id,
                    'success': True,
                    'status': 200,
                    'message': message,
                    'changed': False
                })
                continue

            cursor.execute(
                'UPDATE share_links SET is_active = ? WHERE id = ? AND created_by = ? AND is_active = ?',
                (target_active, share_id, username, share['is_active'])
            )
            if cursor.rowcount != 1:
                conn.rollback()
                results.append({
                    'share_id': share_id,
                    'success': False,
                    'status': 409,
                    'message': '分享状态已变化，请刷新后重试'
                })
                continue

            conn.commit()
            message = '分享链接已停用' if action == 'delete' else '分享链接已恢复'
            results.append({
                'share_id': share_id,
                'success': True,
                'status': 200,
                'message': message,
                'changed': True
            })
        except Exception:
            conn.rollback()
            logger.exception('批量操作分享链接失败: %s', share_id)
            results.append({
                'share_id': share_id,
                'success': False,
                'status': 500,
                'message': '操作失败，请稍后重试'
            })
    conn.close()

    success_count = sum(1 for item in results if item['success'])
    failed_count = len(results) - success_count
    return jsonify({
        'success': failed_count == 0,
        'action': action,
        'total': len(results),
        'success_count': success_count,
        'failed_count': failed_count,
        'results': results
    })


@files_bp.route('/api/share/<share_id>', methods=['DELETE'])
@login_required
def delete_share(share_id):
    """删除分享链接（保留既有本人单条分享流程）"""
    token = get_token_from_request()
    username = get_username_from_token(token)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT created_by, file_id FROM share_links WHERE id = ?', (share_id,))
    share = cursor.fetchone()

    if not share:
        conn.close()
        return jsonify({'error': '分享链接不存在'}), 404

    if share['created_by'] != username:
        conn.close()
        return jsonify({'error': '无权限删除此分享链接'}), 403

    cursor.execute('DELETE FROM share_links WHERE id = ?', (share_id,))
    conn.commit()
    conn.close()

    logger.info(f"分享链接删除: 分享ID {share_id}, 文件ID {share['file_id']}, 操作者 {username}")
    return jsonify({'success': True, 'message': '分享链接已删除'})
