from core.ucoa.app_permission_library import AppPermissionLibrary, PermissionMode
from core.ucoa.notification_center import NotificationCenter

def test_permissions_are_isolated_per_app():
    lib=AppPermissionLibrary(); lib.set_mode('a',PermissionMode.FULL); lib.set_mode('b',PermissionMode.SAFE)
    assert lib.is_allowed('a','delete') is True
    assert lib.is_allowed('b','delete') is False

def test_notifications_are_deduplicated():
    center=NotificationCenter()
    assert center.notify('t','signup','تسجيل','أكمل التسجيل') is True
    assert center.notify('t','signup','تسجيل','أكمل التسجيل') is False
    assert len(center.all())==1
