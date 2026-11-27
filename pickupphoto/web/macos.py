"""AppKit window for the same UI served to the browser."""

from __future__ import annotations

from threading import Event, Lock, Thread

from AppKit import (
    NSAlert, NSApplication, NSApplicationActivationPolicyRegular, NSBackingStoreBuffered,
    NSMakeRect, NSMakeSize, NSMenu, NSMenuItem, NSModalResponseOK, NSOpenPanel,
    NSWindow, NSWindowStyleMaskClosable, NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskResizable, NSWindowStyleMaskTitled, NSTerminateCancel, NSTerminateNow,
)
from Foundation import NSObject, NSURL, NSURLRequest
from PyObjCTools.AppHelper import callAfter
from WebKit import WKWebView, WKWebViewConfiguration, WKWebsiteDataStore

from pickupphoto.web.server import LocalApp


class AppDelegate(NSObject):
    def applicationShouldTerminateAfterLastWindowClosed_(self, _app):
        return True

    def applicationShouldTerminate_(self, _app):
        with self.local_app.lock:
            if self.local_app.job and self.local_app.job["running"]:
                return NSTerminateCancel
            self.local_app.stop.set()
        return NSTerminateNow

    def windowShouldClose_(self, _window):
        with self.local_app.lock:
            busy = self.local_app.job and self.local_app.job["running"]
        if busy:
            alert = NSAlert.alloc().init()
            alert.setMessageText_("請等待目前的工作完成。")
            alert.beginSheetModalForWindow_completionHandler_(self.window, None)
            return False
        return True

    def applicationWillTerminate_(self, _notification):
        self.local_app.shutdown()
        self.local_app.server_close()


class FolderPicker:
    def __init__(self, window):
        self.window = window
        self.lock = Lock()

    def __call__(self):
        if not self.lock.acquire(blocking=False):
            raise ValueError("資料夾選擇器已經開啟。")
        done = Event()
        folder = None

        def show_panel():
            panel = NSOpenPanel.openPanel()
            panel.setCanChooseFiles_(False)
            panel.setCanChooseDirectories_(True)
            panel.setAllowsMultipleSelection_(False)
            panel.setCanCreateDirectories_(True)

            def finish(response):
                nonlocal folder
                if response == NSModalResponseOK:
                    folder = str(panel.URL().path())
                self.lock.release()
                done.set()

            panel.beginSheetModalForWindow_completionHandler_(self.window, finish)

        callAfter(show_panel)
        if not done.wait(300):
            raise ValueError("資料夾選擇已逾時。")
        return folder


def install_menu(app):
    menu = NSMenu.alloc().init()
    app_item = NSMenuItem.alloc().init()
    menu.addItem_(app_item)
    app_menu = NSMenu.alloc().initWithTitle_("PickUpPhoto")
    app_menu.addItemWithTitle_action_keyEquivalent_("Quit PickUpPhoto", "terminate:", "q")
    app_item.setSubmenu_(app_menu)

    edit_item = NSMenuItem.alloc().init()
    menu.addItem_(edit_item)
    edit_menu = NSMenu.alloc().initWithTitle_("Edit")
    for label, action, key in (
        ("Cut", "cut:", "x"), ("Copy", "copy:", "c"), ("Paste", "paste:", "v"),
        ("Select All", "selectAll:", "a"),
    ):
        edit_menu.addItemWithTitle_action_keyEquivalent_(label, action, key)
    edit_item.setSubmenu_(edit_menu)
    app.setMainMenu_(menu)


def run_window(local_app: LocalApp, url: str):
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    install_menu(app)

    style = (
        NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
        | NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable
    )
    window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(0, 0, 1260, 820), style, NSBackingStoreBuffered, False,
    )
    window.setReleasedWhenClosed_(False)
    window.setMinSize_(NSMakeSize(620, 480))
    window.setTitle_("PickUpPhoto")
    window.center()

    configuration = WKWebViewConfiguration.alloc().init()
    configuration.setWebsiteDataStore_(WKWebsiteDataStore.nonPersistentDataStore())
    webview = WKWebView.alloc().initWithFrame_configuration_(window.contentView().bounds(), configuration)
    window.setContentView_(webview)
    window.makeFirstResponder_(webview)
    webview.loadRequest_(NSURLRequest.requestWithURL_(NSURL.URLWithString_(url)))

    delegate = AppDelegate.alloc().init()
    delegate.local_app = local_app
    delegate.window = window
    app.setDelegate_(delegate)
    window.setDelegate_(delegate)
    local_app.folder_picker = FolderPicker(window)

    def serve():
        local_app.serve_forever()
        callAfter(app.terminate_, None)

    Thread(target=serve, daemon=True).start()
    window.makeKeyAndOrderFront_(None)
    app.activateIgnoringOtherApps_(True)
    app.run()
