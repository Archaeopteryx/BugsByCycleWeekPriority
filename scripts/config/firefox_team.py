# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

PRODUCTS_TO_CHECK = [
    'Core',
    'Firefox',
    'Toolkit',
]

# Don't remove products and components renamed later or disabled in Bugzilla.
# They are needed to match these combinations for past dates.
PRODUCTS_COMPONENTS_TO_CHECK = [
    ['Core', 'Window Management'],
    ['Core', 'XUL'],
    ['Firefox', 'about:logins'],
    ['Firefox', 'Address Bar'],
    ['Firefox', 'Bookmarks & History'],
    ['Firefox', 'Downloads Panel'],
    ['Firefox', 'File Handling'],
    ['Firefox', 'General'],
    ['Firefox', 'Keyboard Navigation'],
    ['Firefox', 'Menus'],
    ['Firefox', 'Migration'],
    ['Firefox', 'New Tab Page'],
    ['Firefox', 'Preferences'],
    ['Firefox', 'Protections UI'],
    ['Firefox', 'Screenshots'],
    ['Firefox', 'Search'],
    ['Firefox', 'Session Restore'],
    ['Firefox', 'Settings UI'],
    ['Firefox', 'Site Identity'],
    ['Firefox', 'Site Permissions'],
    ['Firefox', 'Tabbed Browser'],
    ['Firefox', 'Theme'],
    ['Firefox', 'Toolbars and Customization'],
    ['Firefox', 'Top Sites'],
    ['Firefox', 'Tours'],
    ['Firefox', 'View'],
    ['Toolkit', 'Alerts Service'],
    ['Toolkit', 'Content Prompts'],
    ['Toolkit', 'Downloads API'],
    ['Toolkit', 'General'],
    ['Toolkit', 'Notifications and Alerts'], # split up in bug 1838915
    ['Toolkit', 'Picture-in-Picture'],
    ['Toolkit', 'Popup Blocker'],
    ['Toolkit', 'PopupNotifications and Notification Bars'],
    ['Toolkit', 'Preferences'],
    ['Toolkit', 'Printing'],
    ['Toolkit', 'Reader Mode'],
    ['Toolkit', 'Toolbars and Toolbar Customization'],
    ['Toolkit', 'Video/Audio Controls'],
    ['Toolkit', 'XUL Widgets'],
]
