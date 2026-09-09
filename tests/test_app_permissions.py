from core.ucoa.app_permissions import PermissionLibrary, PermissionMode


def test_each_app_has_independent_policy():
    lib=PermissionLibrary()
    lib.set_mode('com.example.browser', PermissionMode.ASK_EVERY_TIME, 'المتصفح')
    lib.set_mode('com.example.editor', PermissionMode.FULL, 'المحرر')
    assert not lib.check('com.example.browser','tap')
    assert lib.check('com.example.browser','tap',explicit_confirmation=True)
    assert lib.check('com.example.editor','tap')
    assert lib.check('com.example.editor','observe')


def test_safe_profile_allows_navigation_but_not_sensitive_actions():
    lib=PermissionLibrary()
    lib.set_mode('com.example.app', PermissionMode.SAFE)
    assert lib.check('com.example.app','open_url')
    assert lib.check('com.example.app','observe')
    assert not lib.check('com.example.app','share_attachment')
