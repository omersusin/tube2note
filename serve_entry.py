"""PyInstaller entry for the Tauri sidecar: `tube2note serve` as a binary."""
import tube2note.cli

if __name__ == "__main__":
    tube2note.cli.main()
