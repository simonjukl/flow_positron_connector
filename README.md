# Positron Projects for Flow Launcher

Search and open [Positron](https://positron.posit.co/) projects from [Flow Launcher](https://www.flowlauncher.com/),
inspired by the Raycast *Visual Studio Code – Project Manager* extension.

## Usage

`pp <search>`. Press Enter to open the project in Positron.

Context menu (Shift+Enter or right-click):

- **Open in new Positron window**
- **Open in Explorer**
- **Copy path**

Results come from three places, with duplicates removed:

1. Projects saved with the [Project Manager](https://marketplace.visualstudio.com/items?itemName=alefragnani.project-manager) extension in Positron (`projects.json`). These show first when the search is empty and rank higher than other matches.
2. Projects Project Manager auto-detected (Git / VS Code / Any), if you enabled detection.
3. Folders and `.code-workspace` files Positron opened recently, newest first. These come from `%APPDATA%\Positron\User\workspaceStorage`.

Search is fuzzy on the project name and tags, and a plain substring match on the path. You can use several words: `pp rko farma`.
Project Manager tags and profiles appear in the subtitle. A project's `profile` is passed to Positron as `--profile`.

## Install

Copy this folder (`plugin.json`, `main.py`, `SettingsTemplate.yaml`, `Images/`) to
`%APPDATA%\FlowLauncher\Plugins\Positron Projects\` and restart Flow Launcher.
The plugin uses only the Python standard library, so Flow's bundled Python is enough.

## Settings

| Setting | Default | |
|---|---|---|
| Positron executable | auto-detect | Path to `Positron.exe` |
| Projects location | auto-detect | Folder containing `projects.json`. Auto-detect reads `projectManager.projectsLocation` from Positron's `settings.json` |
| Include recently opened folders | on | |
| Include auto-detected projects | on | |
| Hide disabled projects | off | Hides saved projects whose `enabled` is `false` |
