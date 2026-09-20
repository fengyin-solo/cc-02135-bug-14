"""文件路由"""
import os
import re
import uuid
import time
import logging
from flask import request, jsonify, send_file
from werkzeug.utils import secure_filename
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
               s.download_count, s.is_disabled, s.created_at,
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

    if share['is_disabled']:
        return False, '分享链接已停用'

    if share['expires_at'] is not None and share['expires_at'] < time.time():
        return False, '分享链接已过期'

    if share['max_downloads'] is not None and share['download_count'] >= share['max_downloads']:
        return False, '分享链接下载次数已用完'

    return True, None


def get_owned_share(cursor, share_id, username):
    """逐条归属判断：返回 (share_row, error_response)。

    - 分享不存在 -> (None, (jsonify({'error': '分享链接不存在'}), 404))
    - 归属他人 -> (None, (jsonify({'error': '无权限操作此分享链接'}), 403))，
      且调用方不得对该记录做任何改动
    - 归属本人 -> (share_row, None)
    """
    cursor.execute(
        'SELECT id, created_by, file_id, is_disabled FROM share_links WHERE id = ?',
        (share_id,)
    )
    share = cursor.fetchone()
    if not share:
        return None, (jsonify({'error': '分享链接不存在'}), 404)
    if share['created_by'] != username:
        return None, (jsonify({'error': '无权限操作此分享链接'}), 403)
    return share, None


def increment_download_count(share_id):
    """增加下载次数"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE share_links SET download_count = download_count + 1 WHERE id = ?',
        (share_id,)
    )
    conn.commit()
    conn.close()


def get_token_from_request():
    """从请求中获取 token"""
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        return auth_header[7:]
    return request.args.get('token')


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
        INSERT INTO share_links (id, file_id, created_by, expires_at, max_downloads)
        VALUES (?, ?, ?, ?, ?)
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

    if not share:
        return jsonify({'error': '分享链接不存在'}), 404

    # 已被所有者停用的分享不得出现在公开访问路径，对外表现为不存在
    if share['is_disabled']:
        return jsonify({'error': '分享链接不存在'}), 404

    valid, error_msg = is_share_valid(share)

    share_data = {
        'share_id': share['id'],
        'filename': share['filename'],
        'filesize': share['filesize'],
        'created_by': share['created_by'],
        'expires_at': share['expires_at'],
        'max_downloads': share['max_downloads'],
        'download_count': share['download_count'],
        'is_disabled': bool(share['is_disabled']),
        'created_at': share['created_at'],
        'is_valid': valid,
        'error_msg': error_msg
    }

    return jsonify(share_data)


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

    increment_download_count(share_id)

    logger.info(f"分享下载: 文件 {file_info['name']}, 分享ID {share_id}, 下载次数 {share['download_count'] + 1}")
    return send_file(file_info['path'], as_attachment=True, download_name=file_info['name'])


@files_bp.route('/api/shares', methods=['GET'])
@login_required
def list_shares():
    """获取当前用户的所有分享链接"""
    token = get_token_from_request()
    username = get_username_from_token(token)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT s.id, s.file_id, s.created_by, s.expires_at, s.max_downloads,
               s.download_count, s.is_disabled, s.created_at,
               f.name as filename, f.size as filesize
        FROM share_links s
        JOIN files f ON s.file_id = f.id
        WHERE s.created_by = ?
        ORDER BY s.created_at DESC
    ''', (username,))
    shares = cursor.fetchall()
    conn.close()

    result = []
    for share in shares:
        valid, error_msg = is_share_valid(share)
        if share['is_disabled']:
            status = 'disabled'
        elif not valid:
            status = 'expired'
        else:
            status = 'active'
        result.append({
            'share_id': share['id'],
            'file_id': share['file_id'],
            'filename': share['filename'],
            'filesize': share['filesize'],
            'expires_at': share['expires_at'],
            'max_downloads': share['max_downloads'],
            'download_count': share['download_count'],
            'is_disabled': bool(share['is_disabled']),
            'status': status,
            'created_at': share['created_at'],
            'is_valid': valid,
            'error_msg': error_msg
        })

    return jsonify(result)


@files_bp.route('/api/share/<share_id>', methods=['DELETE'])
@login_required
def delete_share(share_id):
    """删除分享链接（本人单条流程，行为保持不变）"""
    token = get_token_from_request()
    username = get_username_from_token(token)

    conn = get_db()
    cursor = conn.cursor()
    share, error = get_owned_share(cursor, share_id, username)
    if error:
        conn.close()
        return error

    cursor.execute('DELETE FROM share_links WHERE id = ?', (share_id,))
    conn.commit()
    conn.close()

    logger.info(f"分享链接删除: 分享ID {share_id}, 文件ID {share['file_id']}, 操作者 {username}")
    return jsonify({'success': True, 'message': '分享链接已删除'})


@files_bp.route('/api/share/<share_id>/disable', methods=['POST'])
@login_required
def disable_share(share_id):
    """停用分享链接（本人单条）"""
    token = get_token_from_request()
    username = get_username_from_token(token)

    conn = get_db()
    cursor = conn.cursor()
    share, error = get_owned_share(cursor, share_id, username)
    if error:
        conn.close()
        return error

    cursor.execute('UPDATE share_links SET is_disabled = 1 WHERE id = ?', (share_id,))
    conn.commit()
    conn.close()

    logger.info(f"分享链接停用: 分享ID {share_id}, 操作者 {username}")
    return jsonify({'success': True, 'share_id': share_id, 'is_disabled': True})


@files_bp.route('/api/share/<share_id>/restore', methods=['POST'])
@login_required
def restore_share(share_id):
    """恢复（取消停用）分享链接（本人单条）"""
    token = get_token_from_request()
    username = get_username_from_token(token)

    conn = get_db()
    cursor = conn.cursor()
    share, error = get_owned_share(cursor, share_id, username)
    if error:
        conn.close()
        return error

    cursor.execute('UPDATE share_links SET is_disabled = 0 WHERE id = ?', (share_id,))
    conn.commit()
    conn.close()

    logger.info(f"分享链接恢复: 分享ID {share_id}, 操作者 {username}")
    return jsonify({'success': True, 'share_id': share_id, 'is_disabled': False})


BATCH_ACTIONS = ('delete', 'disable', 'restore')


@files_bp.route('/api/shares/batch', methods=['POST'])
@login_required
def batch_operate_shares():
    """批量删除/停用/恢复分享链接。

    逐条归属判断：无权限或不存在的项逐条拒绝（403/404），绝不改动；
    其余项逐条执行。返回 total/succeeded/failed 与每个 share_id 的结果，
    三者数量始终与去重后的提交项总数一致。
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': '无效的请求数据'}), 400

    action = data.get('action')
    share_ids = data.get('share_ids')

    if action not in BATCH_ACTIONS:
        return jsonify({'error': '不支持的批量操作'}), 400

    if not isinstance(share_ids, list) or not share_ids:
        return jsonify({'error': '请至少选择一条分享记录'}), 400

    # 校验并按提交顺序去重：任何非字符串/空白 ID 都属于非法请求，整体拒绝，
    # 保证返回的 total 与实际处理项严格一致
    unique_ids = []
    seen = set()
    for raw_id in share_ids:
        if not isinstance(raw_id, str):
            return jsonify({'error': '分享ID格式无效'}), 400
        sid = raw_id.strip()
        if not sid:
            return jsonify({'error': '分享ID不能为空'}), 400
        if sid not in seen:
            seen.add(sid)
            unique_ids.append(sid)

    if len(unique_ids) > 100:
        return jsonify({'error': '单次最多操作 100 条分享记录'}), 400

    token = get_token_from_request()
    username = get_username_from_token(token)

    conn = get_db()
    cursor = conn.cursor()

    results = []
    succeeded = 0
    failed = 0

    for sid in unique_ids:
        # 每个 share_id 都独立查询并做归属判断，不能用一次批量 UPDATE 绕过
        share, error = get_owned_share(cursor, sid, username)
        if error:
            response, status_code = error
            results.append({
                'share_id': sid,
                'success': False,
                'code': status_code,
                'error': response.get_json()['error']
            })
            failed += 1
            continue

        try:
            if action == 'delete':
                cursor.execute('DELETE FROM share_links WHERE id = ?', (sid,))
            elif action == 'disable':
                cursor.execute('UPDATE share_links SET is_disabled = 1 WHERE id = ?', (sid,))
            else:  # restore
                cursor.execute('UPDATE share_links SET is_disabled = 0 WHERE id = ?', (sid,))
            conn.commit()
        except Exception:
            conn.rollback()
            logger.exception(f'批量{action}分享失败: 分享ID {sid}, 操作者 {username}')
            results.append({
                'share_id': sid,
                'success': False,
                'code': 500,
                'error': '操作失败'
            })
            failed += 1
            continue

        results.append({'share_id': sid, 'success': True, 'code': 200})
        succeeded += 1

    conn.close()

    logger.info(
        f'批量{action}分享: 操作者 {username}, 总数 {len(unique_ids)}, '
        f'成功 {succeeded}, 失败 {failed}'
    )

    return jsonify({
        'success': True,
        'action': action,
        'total': len(unique_ids),
        'succeeded': succeeded,
        'failed': failed,
        'results': results
    })
