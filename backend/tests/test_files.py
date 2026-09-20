"""文件模块测试"""
import io
import time

import pytest


def test_upload_file(client):
    """测试文件上传"""
    data = {
        'file': (io.BytesIO(b'test content'), 'test.txt')
    }
    response = client.post('/api/upload', data=data, content_type='multipart/form-data')
    assert response.status_code == 200
    result = response.get_json()
    assert result['success'] is True
    assert 'file_id' in result


def test_upload_no_file(client):
    """测试无文件上传"""
    response = client.post('/api/upload', data={}, content_type='multipart/form-data')
    assert response.status_code == 400


def test_upload_invalid_extension(client):
    """测试不允许的文件类型"""
    data = {
        'file': (io.BytesIO(b'test'), 'test.exe')
    }
    response = client.post('/api/upload', data=data, content_type='multipart/form-data')
    assert response.status_code == 400


def test_list_files(client):
    """测试文件列表"""
    response = client.get('/api/files')
    assert response.status_code == 200
    assert isinstance(response.get_json(), list)


def test_download_without_token(client):
    """测试无 token 下载"""
    response = client.get('/api/download/some-id')
    assert response.status_code == 401


def test_download_file_not_found(client, auth_token):
    """测试下载不存在的文件"""
    response = client.get(f'/api/download/nonexistent-id?token={auth_token}')
    assert response.status_code == 404


def test_upload_and_download(client, auth_token):
    """测试上传后下载"""
    # 上传
    data = {
        'file': (io.BytesIO(b'hello world'), 'hello.txt')
    }
    upload_resp = client.post('/api/upload', data=data, content_type='multipart/form-data')
    file_id = upload_resp.get_json()['file_id']

    # 下载
    download_resp = client.get(f'/api/download/{file_id}?token={auth_token}')
    assert download_resp.status_code == 200
    assert download_resp.data == b'hello world'


def test_create_share_without_auth(client):
    """测试未授权创建分享链接"""
    response = client.post('/api/share', json={'file_id': 'test'})
    assert response.status_code == 401


def test_create_share_invalid_file(client, auth_token):
    """测试为不存在的文件创建分享链接"""
    response = client.post(
        '/api/share',
        json={'file_id': 'nonexistent'},
        headers={'Authorization': f'Bearer {auth_token}'}
    )
    assert response.status_code == 404


def test_create_share_success(client, auth_token):
    """测试创建分享链接成功"""
    data = {'file': (io.BytesIO(b'test content'), 'test_share.txt')}
    upload_resp = client.post('/api/upload', data=data, content_type='multipart/form-data')
    file_id = upload_resp.get_json()['file_id']

    response = client.post(
        '/api/share',
        json={'file_id': file_id, 'expire_hours': 24, 'max_downloads': 5},
        headers={'Authorization': f'Bearer {auth_token}'}
    )
    assert response.status_code == 200
    result = response.get_json()
    assert result['success'] is True
    assert 'share_id' in result
    assert result['max_downloads'] == 5
    assert result['filename'] == 'test_share.txt'


def test_create_share_default_values(client, auth_token):
    """测试使用默认值创建分享链接"""
    data = {'file': (io.BytesIO(b'test content'), 'test_default.txt')}
    upload_resp = client.post('/api/upload', data=data, content_type='multipart/form-data')
    file_id = upload_resp.get_json()['file_id']

    response = client.post(
        '/api/share',
        json={'file_id': file_id},
        headers={'Authorization': f'Bearer {auth_token}'}
    )
    assert response.status_code == 200
    result = response.get_json()
    assert result['success'] is True
    assert result['max_downloads'] == 10


def test_get_share_info(client, auth_token):
    """测试获取分享链接信息"""
    data = {'file': (io.BytesIO(b'test content'), 'test_get.txt')}
    upload_resp = client.post('/api/upload', data=data, content_type='multipart/form-data')
    file_id = upload_resp.get_json()['file_id']

    create_resp = client.post(
        '/api/share',
        json={'file_id': file_id, 'expire_hours': 24, 'max_downloads': 5},
        headers={'Authorization': f'Bearer {auth_token}'}
    )
    share_id = create_resp.get_json()['share_id']

    response = client.get(f'/api/share/{share_id}')
    assert response.status_code == 200
    result = response.get_json()
    assert result['share_id'] == share_id
    assert result['filename'] == 'test_get.txt'
    assert result['is_valid'] is True
    assert result['download_count'] == 0


def test_get_nonexistent_share(client):
    """测试获取不存在的分享链接"""
    response = client.get('/api/share/nonexistent')
    assert response.status_code == 404


def test_download_by_share_success(client, auth_token):
    """测试通过分享链接下载文件成功"""
    data = {'file': (io.BytesIO(b'share download test'), 'test_share_dl.txt')}
    upload_resp = client.post('/api/upload', data=data, content_type='multipart/form-data')
    file_id = upload_resp.get_json()['file_id']

    create_resp = client.post(
        '/api/share',
        json={'file_id': file_id, 'expire_hours': 24, 'max_downloads': 5},
        headers={'Authorization': f'Bearer {auth_token}'}
    )
    share_id = create_resp.get_json()['share_id']

    download_resp = client.get(f'/api/share/{share_id}/download')
    assert download_resp.status_code == 200
    assert download_resp.data == b'share download test'

    info_resp = client.get(f'/api/share/{share_id}')
    assert info_resp.get_json()['download_count'] == 1


def test_download_by_share_exceed_max(client, auth_token):
    """测试超过下载次数限制"""
    data = {'file': (io.BytesIO(b'limited content'), 'test_limited.txt')}
    upload_resp = client.post('/api/upload', data=data, content_type='multipart/form-data')
    file_id = upload_resp.get_json()['file_id']

    create_resp = client.post(
        '/api/share',
        json={'file_id': file_id, 'expire_hours': 24, 'max_downloads': 1},
        headers={'Authorization': f'Bearer {auth_token}'}
    )
    share_id = create_resp.get_json()['share_id']

    download_resp1 = client.get(f'/api/share/{share_id}/download')
    assert download_resp1.status_code == 200

    download_resp2 = client.get(f'/api/share/{share_id}/download')
    assert download_resp2.status_code == 404
    assert '下载次数已用完' in download_resp2.get_json()['error']


def test_download_expired_share(client, auth_token, db_conn):
    """测试下载已过期的分享链接"""
    data = {'file': (io.BytesIO(b'expired content'), 'test_expired.txt')}
    upload_resp = client.post('/api/upload', data=data, content_type='multipart/form-data')
    file_id = upload_resp.get_json()['file_id']

    create_resp = client.post(
        '/api/share',
        json={'file_id': file_id, 'expire_hours': 1, 'max_downloads': 5},
        headers={'Authorization': f'Bearer {auth_token}'}
    )
    share_id = create_resp.get_json()['share_id']

    cursor = db_conn.cursor()
    cursor.execute(
        'UPDATE share_links SET expires_at = ? WHERE id = ?',
        (time.time() - 3600, share_id)
    )
    db_conn.commit()

    download_resp = client.get(f'/api/share/{share_id}/download')
    assert download_resp.status_code == 404
    assert '已过期' in download_resp.get_json()['error']


def test_create_share_unlimited(client, auth_token):
    """测试创建无限制的分享链接"""
    data = {'file': (io.BytesIO(b'unlimited content'), 'test_unlimited.txt')}
    upload_resp = client.post('/api/upload', data=data, content_type='multipart/form-data')
    file_id = upload_resp.get_json()['file_id']

    create_resp = client.post(
        '/api/share',
        json={'file_id': file_id, 'expire_hours': -1, 'max_downloads': -1},
        headers={'Authorization': f'Bearer {auth_token}'}
    )
    result = create_resp.get_json()
    assert result['expires_at'] is None
    assert result['max_downloads'] is None

    for i in range(3):
        download_resp = client.get(f'/api/share/{result["share_id"]}/download')
        assert download_resp.status_code == 200

    info_resp = client.get(f'/api/share/{result["share_id"]}')
    assert info_resp.get_json()['download_count'] == 3
    assert info_resp.get_json()['is_valid'] is True


def test_list_shares(client, auth_token):
    """测试获取用户的分享列表"""
    for i in range(2):
        data = {'file': (io.BytesIO(f'content {i}'.encode()), f'test_list_{i}.txt')}
        upload_resp = client.post('/api/upload', data=data, content_type='multipart/form-data')
        file_id = upload_resp.get_json()['file_id']

        client.post(
            '/api/share',
            json={'file_id': file_id},
            headers={'Authorization': f'Bearer {auth_token}'}
        )

    response = client.get(
        '/api/shares',
        headers={'Authorization': f'Bearer {auth_token}'}
    )
    assert response.status_code == 200
    shares = response.get_json()
    assert len(shares) >= 2
    assert 'filename' in shares[0]
    assert 'is_valid' in shares[0]


def test_list_shares_without_auth(client):
    """测试未授权获取分享列表"""
    response = client.get('/api/shares')
    assert response.status_code == 401


def test_delete_share_success(client, auth_token):
    """测试删除分享链接成功"""
    data = {'file': (io.BytesIO(b'to delete'), 'test_delete.txt')}
    upload_resp = client.post('/api/upload', data=data, content_type='multipart/form-data')
    file_id = upload_resp.get_json()['file_id']

    create_resp = client.post(
        '/api/share',
        json={'file_id': file_id},
        headers={'Authorization': f'Bearer {auth_token}'}
    )
    share_id = create_resp.get_json()['share_id']

    delete_resp = client.delete(
        f'/api/share/{share_id}',
        headers={'Authorization': f'Bearer {auth_token}'}
    )
    assert delete_resp.status_code == 200
    assert delete_resp.get_json()['success'] is True

    get_resp = client.get(f'/api/share/{share_id}')
    assert get_resp.status_code == 404


def test_delete_share_unauthorized(client, auth_token, db_conn):
    """测试删除他人的分享链接"""
    data = {'file': (io.BytesIO(b'other content'), 'test_other.txt')}
    upload_resp = client.post('/api/upload', data=data, content_type='multipart/form-data')
    file_id = upload_resp.get_json()['file_id']

    cursor = db_conn.cursor()
    cursor.execute(
        'INSERT INTO share_links (id, file_id, created_by, expires_at, max_downloads) VALUES (?, ?, ?, ?, ?)',
        ('testshare123', file_id, 'otheruser', None, 10)
    )
    db_conn.commit()

    delete_resp = client.delete(
        '/api/share/testshare123',
        headers={'Authorization': f'Bearer {auth_token}'}
    )
    assert delete_resp.status_code == 403


def _get_auth_headers(token):
    return {'Authorization': f'Bearer {token}'}


def _create_share(client, token, filename='batch-file.txt', content=b'batch content', created_by=None, is_active=1):
    upload_resp = client.post(
        '/api/upload',
        data={'file': (io.BytesIO(content), filename)},
        content_type='multipart/form-data'
    )
    file_id = upload_resp.get_json()['file_id']

    if created_by is None:
        create_resp = client.post(
            '/api/share',
            json={'file_id': file_id},
            headers=_get_auth_headers(token)
        )
        return create_resp.get_json()['share_id']

    from database import get_db
    share_id = f'share-{created_by}-{file_id[:8]}'
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        '''INSERT INTO share_links
           (id, file_id, created_by, expires_at, max_downloads, is_active)
           VALUES (?, ?, ?, NULL, 10, ?)''',
        (share_id, file_id, created_by, is_active)
    )
    conn.commit()
    conn.close()
    return share_id


def test_batch_delete_disables_own_shares_and_blocks_public_access(client, auth_token):
    first_id = _create_share(client, auth_token, filename='first.txt', content=b'1')
    second_id = _create_share(client, auth_token, filename='second.txt', content=b'2')

    response = client.post(
        '/api/shares/batch',
        json={'action': 'delete', 'share_ids': [first_id, second_id]},
        headers=_get_auth_headers(auth_token)
    )

    assert response.status_code == 200
    result = response.get_json()
    assert result['total'] == 2
    assert result['success_count'] == 2
    assert result['failed_count'] == 0
    assert all(item['success'] for item in result['results'])

    for share_id in (first_id, second_id):
        assert client.get(f'/api/share/{share_id}').status_code == 404
        assert client.get(f'/api/share/{share_id}/download').status_code == 404

    shares = client.get('/api/shares', headers=_get_auth_headers(auth_token)).get_json()
    updated = {share['share_id']: share for share in shares if share['share_id'] in (first_id, second_id)}
    assert all(share['is_active'] is False for share in updated.values())


def test_batch_delete_rejects_each_unauthorized_share_without_change(client, auth_token):
    own_id = _create_share(client, auth_token, filename='own.txt', content=b'own')
    other_id = _create_share(
        client,
        auth_token,
        filename='other.txt',
        content=b'other',
        created_by='otheruser'
    )

    response = client.post(
        '/api/shares/batch',
        json={'action': 'delete', 'share_ids': [own_id, other_id]},
        headers=_get_auth_headers(auth_token)
    )

    assert response.status_code == 200
    result = response.get_json()
    assert result['total'] == 2
    assert result['success_count'] == 1
    assert result['failed_count'] == 1
    statuses = {item['share_id']: item for item in result['results']}
    assert statuses[own_id]['success'] is True
    assert statuses[other_id]['success'] is False
    assert statuses[other_id]['status'] == 403

    from database import get_db
    conn = get_db()
    states = dict(conn.execute(
        'SELECT id, is_active FROM share_links WHERE id IN (?, ?)',
        (own_id, other_id)
    ).fetchall())
    conn.close()
    assert states == {own_id: 0, other_id: 1}
    assert client.get(f'/api/share/{other_id}').status_code == 200


def test_batch_restore_reactivates_only_owned_disabled_shares(client, auth_token, db_conn):
    own_id = _create_share(
        client,
        auth_token,
        filename='disabled-own.txt',
        content=b'disabled own',
        created_by='admin',
        is_active=0
    )
    other_id = _create_share(
        client,
        auth_token,
        filename='disabled-other.txt',
        content=b'disabled other',
        created_by='otheruser',
        is_active=0
    )
    missing_id = 'missing-share-id'

    response = client.post(
        '/api/shares/batch',
        json={'action': 'restore', 'share_ids': [own_id, other_id, missing_id]},
        headers=_get_auth_headers(auth_token)
    )

    result = response.get_json()
    assert result['total'] == 3
    assert result['success_count'] == 1
    assert result['failed_count'] == 2
    statuses = {item['share_id']: item for item in result['results']}
    assert statuses[own_id]['success'] is True
    assert statuses[other_id]['status'] == 403
    assert statuses[missing_id]['status'] == 404
    assert client.get(f'/api/share/{own_id}').status_code == 200
    assert client.get(f'/api/share/{other_id}').status_code == 404

    cursor = db_conn.cursor()
    states = dict(cursor.execute(
        'SELECT id, is_active FROM share_links WHERE id IN (?, ?)',
        (own_id, other_id)
    ).fetchall())
    assert states == {own_id: 1, other_id: 0}


def test_batch_action_deduplicates_ids_and_keeps_result_count_consistent(client, auth_token):
    share_id = _create_share(client, auth_token, filename='dup.txt', content=b'dup')

    response = client.post(
        '/api/shares/batch',
        json={'action': 'delete', 'share_ids': [share_id, share_id, f' {share_id} ']},
        headers=_get_auth_headers(auth_token)
    )

    result = response.get_json()
    assert response.status_code == 200
    assert result['total'] == 1
    assert result['success_count'] == 1
    assert result['failed_count'] == 0
    assert len(result['results']) == 1


@pytest.mark.parametrize('payload', [
    {'action': 'unknown', 'share_ids': ['x']},
    {'action': 'delete', 'share_ids': []},
    {'action': 'delete', 'share_ids': 'not-an-array'},
    {'action': 'delete', 'share_ids': ['']},
])
def test_batch_action_rejects_invalid_payload(client, auth_token, payload):
    response = client.post(
        '/api/shares/batch',
        json=payload,
        headers=_get_auth_headers(auth_token)
    )
    assert response.status_code == 400


def test_batch_action_requires_auth(client):
    response = client.post('/api/shares/batch', json={'action': 'delete', 'share_ids': ['x']})
    assert response.status_code == 401


def test_batch_operation_does_not_change_single_delete_flow(client, auth_token):
    share_id = _create_share(client, auth_token, filename='single-flow.txt', content=b'single')

    response = client.delete(
        f'/api/share/{share_id}',
        headers=_get_auth_headers(auth_token)
    )

    assert response.status_code == 200
    assert response.get_json()['success'] is True
    assert client.get(f'/api/share/{share_id}').status_code == 404
    from database import get_db
    conn = get_db()
    count = conn.execute('SELECT COUNT(*) FROM share_links WHERE id = ?', (share_id,)).fetchone()[0]
    conn.close()
    assert count == 0


def test_download_by_share_no_auth_needed(client, auth_token):
    """测试访客无需登录即可通过分享链接下载"""
    data = {'file': (io.BytesIO(b'public content'), 'test_public.txt')}
    upload_resp = client.post('/api/upload', data=data, content_type='multipart/form-data')
    file_id = upload_resp.get_json()['file_id']

    create_resp = client.post(
        '/api/share',
        json={'file_id': file_id, 'expire_hours': 24, 'max_downloads': 5},
        headers={'Authorization': f'Bearer {auth_token}'}
    )
    share_id = create_resp.get_json()['share_id']

    download_resp = client.get(f'/api/share/{share_id}/download')
    assert download_resp.status_code == 200
    assert download_resp.data == b'public content'
