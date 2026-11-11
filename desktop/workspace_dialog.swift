// Native file panels run on their own main thread, outside the HTTP worker.
import AppKit
import UniformTypeIdentifiers

let args = Array(CommandLine.arguments.dropFirst())
func option(_ key: String) -> String? {
    guard let index = args.firstIndex(of: key), index + 1 < args.count else { return nil }
    return args[index + 1]
}
let app = NSApplication.shared
app.setActivationPolicy(.regular)
app.finishLaunching()
let opening = args.contains("--open")
let panel: NSSavePanel
if opening {
    let open = NSOpenPanel()
    open.canChooseFiles = true
    open.canChooseDirectories = false
    open.allowsMultipleSelection = false
    panel = open
} else {
    panel = NSSavePanel()
    panel.nameFieldStringValue = option("--name") ?? "Workspace.pepper"
    panel.canCreateDirectories = true
}
panel.title = opening ? "Open Salt and Pepper workspace" : "Save Salt and Pepper workspace"
panel.prompt = opening ? "Open" : "Save"
panel.allowedContentTypes = [UTType(filenameExtension: "pepper") ?? .data]
panel.allowsOtherFileTypes = false
panel.isExtensionHidden = false
panel.canSelectHiddenExtension = false
if let directory = option("--directory") {
    panel.directoryURL = URL(fileURLWithPath: directory, isDirectory: true)
}
app.activate(ignoringOtherApps: true)
let response = panel.runModal()
var result: [String: String] = ["status": "cancelled"]
if response == .OK, let url = panel.url {
    result = ["status": "selected", "path": url.path]
}
// Return focus to the actual desktop app without System Events/Automation access.
if let owner = option("--owner-pid"), let pid = Int32(owner),
   let parent = NSRunningApplication(processIdentifier: pid) {
    parent.activate(options: [])
}
let data = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
FileHandle.standardOutput.write(data)
FileHandle.standardOutput.write(Data([10]))
