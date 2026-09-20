"""文件模块测试"""
import io
import time
import uuid


def _create_share(client, auth_token, filename='file.txt', content=b'data',
                  expire_hours=24, max_downloads=5):
    """上传文件并创建分享，返回 (file_id, share_id)"""
    data = {'file': (io.BytesIO(content), filename)}
    upload_resp = client.post('/api/upload', data=data, content_type='multipart/form-data')
    file_id = upload_resp.get_json()['file_id']

    create_resp = client.post(
        '/api/share',
        json={'file_id': file_id, 'expire_hours': expire_hours,
              'max_downloads': max_downloads},
        headers={'Authorization': f'Bearer {auth_token}'}
    )
    return file_id, create_resp.get_json()['share_id']


def _insert_foreign_share(db_conn, file_id, created_by='otheruser', share_id=None):
    """直接写入一条他人的分享记录（含已停用场景）"""
    share_id = share_id or uuid.uuid4().hex[:12]
    cursor = db_conn.cursor()
    cursor.execute(
        '''INSERT INTO share_links
           (id, file_id, created_by, expires_at, max_downloads, is_disabled)
           VALUES (?, ?, ?, ?, ?, ?)''',
        (share_id, file_id, created_by, None, 10, 0)
    )
    db_conn.commit()
    return share_id


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


# ---------------- 停用 / 恢复 ----------------

def test_disable_share_blocks_public_access(client, auth_token):
    """停用后公开详情与下载路径均不可访问"""
    _, share_id = _create_share(client, auth_token, filename='disabled.txt')

    resp = client.post(
        f'/api/share/{share_id}/disable',
        headers={'Authorization': f'Bearer {auth_token}'}
    )
    assert resp.status_code == 200
    assert resp.get_json()['is_disabled'] is True

    # 详情接口对访客表现为不存在
    assert client.get(f'/api/share/{share_id}').status_code == 404
    # 下载路径同样拦截
    assert client.get(f'/api/share/{share_id}/download').status_code == 404


def test_restore_disabled_share(client, auth_token):
    """恢复后分享重新可用"""
    _, share_id = _create_share(client, auth_token, filename='restored.txt')

    client.post(
        f'/api/share/{share_id}/disable',
        headers={'Authorization': f'Bearer {auth_token}'}
    )
    assert client.get(f'/api/share/{share_id}').status_code == 404

    resp = client.post(
        f'/api/share/{share_id}/restore',
        headers={'Authorization': f'Bearer {auth_token}'}
    )
    assert resp.status_code == 200
    assert resp.get_json()['is_disabled'] is False

    info = client.get(f'/api/share/{share_id}')
    assert info.status_code == 200
    assert info.get_json()['is_valid'] is True


def test_disable_other_users_share_forbidden(client, auth_token, db_conn):
    """单条停用他人分享 -> 403，且记录不被改动"""
    data = {'file': (io.BytesIO(b'x'), 'foreign.txt')}
    file_id = client.post(
        '/api/upload', data=data, content_type='multipart/form-data'
    ).get_json()['file_id']
    foreign_id = _insert_foreign_share(db_conn, file_id)

    resp = client.post(
        f'/api/share/{foreign_id}/disable',
        headers={'Authorization': f'Bearer {auth_token}'}
    )
    assert resp.status_code == 403

    cursor = db_conn.cursor()
    cursor.execute('SELECT is_disabled FROM share_links WHERE id = ?', (foreign_id,))
    assert cursor.fetchone()[0] == 0


def test_restore_other_users_share_forbidden(client, auth_token, db_conn):
    """单条恢复他人分享 -> 403，且记录不被改动"""
    data = {'file': (io.BytesIO(b'x'), 'foreign2.txt')}
    file_id = client.post(
        '/api/upload', data=data, content_type='multipart/form-data'
    ).get_json()['file_id']
    foreign_id = uuid.uuid4().hex[:12]
    cursor = db_conn.cursor()
    cursor.execute(
        '''INSERT INTO share_links
           (id, file_id, created_by, expires_at, max_downloads, is_disabled)
           VALUES (?, ?, ?, ?, ?, 1)''',
        (foreign_id, file_id, 'otheruser', None, 10)
    )
    db_conn.commit()

    resp = client.post(
        f'/api/share/{foreign_id}/restore',
        headers={'Authorization': f'Bearer {auth_token}'}
    )
    assert resp.status_code == 403

    cursor.execute('SELECT is_disabled FROM share_links WHERE id = ?', (foreign_id,))
    assert cursor.fetchone()[0] == 1


def test_disable_nonexistent_share(client, auth_token):
    """停用不存在的分享 -> 404"""
    resp = client.post(
        '/api/share/nonexistent-id/disable',
        headers={'Authorization': f'Bearer {auth_token}'}
    )
    assert resp.status_code == 404


def test_batch_disable_requires_auth(client):
    """批量接口需要登录"""
    resp = client.post('/api/shares/batch', json={'action': 'delete', 'share_ids': ['x']})
    assert resp.status_code == 401


def test_batch_invalid_action(client, auth_token):
    """不支持的批量动作 -> 400"""
    resp = client.post(
        '/api/shares/batch',
        json={'action': 'hack', 'share_ids': ['x']},
        headers={'Authorization': f'Bearer {auth_token}'}
    )
    assert resp.status_code == 400


def test_batch_empty_selection(client, auth_token):
    """未选择任何项 -> 400"""
    resp = client.post(
        '/api/shares/batch',
        json={'action': 'delete', 'share_ids': []},
        headers={'Authorization': f'Bearer {auth_token}'}
    )
    assert resp.status_code == 400


def test_batch_delete_mixed_ownership(client, auth_token, db_conn):
    """批量删除混入他人/不存在记录：本人项执行，其余逐条拒绝且不改动，
    返回 total = succeeded + failed 且与提交项数一致"""
    _, own1 = _create_share(client, auth_token, filename='own1.txt')
    _, own2 = _create_share(client, auth_token, filename='own2.txt')

    data = {'file': (io.BytesIO(b'x'), 'foreign3.txt')}
    file_id = client.post(
        '/api/upload', data=data, content_type='multipart/form-data'
    ).get_json()['file_id']
    foreign_id = _insert_foreign_share(db_conn, file_id)
    missing_id = 'does-not-exist'

    submitted = [own1, foreign_id, own2, missing_id]
    resp = client.post(
        '/api/shares/batch',
        json={'action': 'delete', 'share_ids': submitted},
        headers={'Authorization': f'Bearer {auth_token}'}
    )
    assert resp.status_code == 200
    result = resp.get_json()

    assert result['total'] == 4
    assert result['succeeded'] == 2
    assert result['failed'] == 2
    assert result['total'] == result['succeeded'] + result['failed']

    by_id = {item['share_id']: item for item in result['results']}
    assert by_id[own1]['success'] is True
    assert by_id[own2]['success'] is True
    assert by_id[foreign_id]['success'] is False
    assert by_id[foreign_id]['code'] == 403
    assert by_id[missing_id]['success'] is False
    assert by_id[missing_id]['code'] == 404

    # 本人记录已删除
    assert client.get(f'/api/share/{own1}').status_code == 404
    assert client.get(f'/api/share/{own2}').status_code == 404
    # 他人记录原样保留
    cursor = db_conn.cursor()
    cursor.execute('SELECT id FROM share_links WHERE id = ?', (foreign_id,))
    assert cursor.fetchone() is not None
    # 访客仍可访问未被改动的他人分享
    assert client.get(f'/api/share/{foreign_id}').status_code == 200


def test_batch_disable_then_restore_own(client, auth_token):
    """批量停用/恢复本人分享：结果数与总数一致，公开访问随之变化"""
    _, s1 = _create_share(client, auth_token, filename='b1.txt')
    _, s2 = _create_share(client, auth_token, filename='b2.txt')

    resp = client.post(
        '/api/shares/batch',
        json={'action': 'disable', 'share_ids': [s1, s2]},
        headers={'Authorization': f'Bearer {auth_token}'}
    )
    result = resp.get_json()
    assert result['total'] == 2
    assert result['succeeded'] == 2
    assert result['failed'] == 0

    assert client.get(f'/api/share/{s1}').status_code == 404
    assert client.get(f'/api/share/{s2}/download').status_code == 404

    # 管理列表中状态为 disabled
    shares = client.get(
        '/api/shares',
        headers={'Authorization': f'Bearer {auth_token}'}
    ).get_json()
    by_id = {s['share_id']: s for s in shares}
    assert by_id[s1]['status'] == 'disabled'
    assert by_id[s1]['is_disabled'] is True

    resp = client.post(
        '/api/shares/batch',
        json={'action': 'restore', 'share_ids': [s1, s2]},
        headers={'Authorization': f'Bearer {auth_token}'}
    )
    assert resp.get_json()['succeeded'] == 2

    assert client.get(f'/api/share/{s1}').status_code == 200
    assert client.get(f'/api/share/{s2}/download').status_code == 200


def test_batch_deduplicates_ids(client, auth_token):
    """重复提交同一 ID 时按去重后计数，total 与返回明细一致"""
    _, share_id = _create_share(client, auth_token, filename='dup.txt')

    resp = client.post(
        '/api/shares/batch',
        json={'action': 'disable', 'share_ids': [share_id, share_id]},
        headers={'Authorization': f'Bearer {auth_token}'}
    )
    result = resp.get_json()
    assert result['total'] == 1
    assert len(result['results']) == 1


def test_batch_all_forbidden_changes_nothing(client, auth_token, db_conn):
    """全部无权限时：逐条 403，整体 HTTP 200，数据库无任何改动"""
    data = {'file': (io.BytesIO(b'x'), 'foreign4.txt')}
    file_id = client.post(
        '/api/upload', data=data, content_type='multipart/form-data'
    ).get_json()['file_id']
    foreign_id = _insert_foreign_share(db_conn, file_id)

    resp = client.post(
        '/api/shares/batch',
        json={'action': 'disable', 'share_ids': [foreign_id]},
        headers={'Authorization': f'Bearer {auth_token}'}
    )
    assert resp.status_code == 200
    result = resp.get_json()
    assert result['succeeded'] == 0
    assert result['failed'] == 1
    assert result['results'][0]['code'] == 403

    cursor = db_conn.cursor()
    cursor.execute('SELECT is_disabled FROM share_links WHERE id = ?', (foreign_id,))
    assert cursor.fetchone()[0] == 0


def test_single_share_flow_unaffected(client, auth_token):
    """既有本人单条创建-复制链接-删除流程不受影响"""
    _, share_id = _create_share(client, auth_token, filename='single.txt')

    info = client.get(f'/api/share/{share_id}')
    assert info.status_code == 200
    assert info.get_json()['is_valid'] is True

    deleted = client.delete(
        f'/api/share/{share_id}',
        headers={'Authorization': f'Bearer {auth_token}'}
    )
    assert deleted.status_code == 200
    assert client.get(f'/api/share/{share_id}').status_code == 404


def test_batch_invalid_id_type(client, auth_token):
    """非法 ID（非字符串/空白）整体 400，不执行任何操作"""
    resp = client.post(
        '/api/shares/batch',
        json={'action': 'delete', 'share_ids': ['ok-id', 123]},
        headers={'Authorization': f'Bearer {auth_token}'}
    )
    assert resp.status_code == 400

    resp = client.post(
        '/api/shares/batch',
        json={'action': 'delete', 'share_ids': ['   ']},
        headers={'Authorization': f'Bearer {auth_token}'}
    )
    assert resp.status_code == 400
