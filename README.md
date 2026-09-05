# Dotfiles

Personal dotfiles for macOS, optimized for PHP/Laravel development with Valet.

## What's Included

- **Shell**: Zsh with Oh My Zsh, Starship prompt, and modern CLI tools
- **Editor**: Zed configuration with PHP formatting via Pint
- **Git**: Delta for diffs, sensible aliases, global gitignore
- **PHP/Laravel**: Valet-based workflow with PHP Monitor
- **Node**: FNM (Fast Node Manager) instead of NVM
- **Claude Code**: Skills, agents, and settings
- **Linux dev workstation**: Reproducible task runner, workstation doctor, and worktree retention/inode tooling (see [Linux dev-workstation docs](docs/dev-workstation.md) and [worktree retention](docs/worktree-retention.md))

## Quick Start

```bash
# 1. Clone to ~/.dotfiles
git clone git@github.com:deinte/dotfiles.git ~/.dotfiles

# 2. Run installer
~/.dotfiles/bin/install

# 3. (Optional) Apply macOS defaults
~/.dotfiles/macos/set-defaults.sh

# 4. Restart terminal
exec zsh
```

## Directory Structure

```
~/.dotfiles/
├── bin/
│   ├── install         # Main installation script
│   ├── update          # Update all packages
│   ├── php-format      # PHP formatter for Zed
│   ├── agent-task      # Linux task lifecycle runner
│   ├── install-linux-devstation
│   ├── workstation-sync
│   ├── workstation-doctor
│   └── worktree-gc         # worktree retention inventory + inode alerting
├── config/
│   ├── Brewfile        # Homebrew packages
│   ├── starship.toml   # Prompt configuration
│   ├── claude/         # Claude Code config
│   └── zed/            # Zed editor settings
├── home/
│   ├── .zshrc          # Shell configuration
│   ├── .aliases        # Shell aliases
│   ├── .functions      # Shell functions
│   ├── .exports        # Environment variables
│   ├── .gitconfig      # Git configuration
│   ├── .global-gitignore
│   └── .vimrc          # Vim configuration
└── macos/
    └── set-defaults.sh # macOS system preferences
```

## Installed Tools

### CLI Tools (via Homebrew)

| Tool | Replaces | Description |
|------|----------|-------------|
| `eza` | `ls` | Better file listing with icons |
| `bat` | `cat` | Syntax highlighted file viewing |
| `ripgrep` | `grep` | Fast code searching |
| `fd` | `find` | User-friendly file finder |
| `zoxide` | `cd` | Smart directory jumping |
| `bottom` | `htop` | System monitor |
| `delta` | `diff` | Beautiful git diffs |
| `fnm` | `nvm` | Fast Node version manager |
| `fzf` | - | Fuzzy finder |
| `starship` | - | Modern shell prompt |

### GUI Apps

- **Warp** - Modern terminal
- **Zed** - Fast code editor
- **JetBrains Toolbox** - PhpStorm, etc.
- **PHP Monitor** - PHP version switcher
- **DBngin** - Database server manager
- **TablePlus** - Database GUI
- **Ray** - Laravel debugging
- **Raycast** - Spotlight replacement
- **Claude Code** - AI assistant

## Key Aliases

### PHP/Laravel
```bash
a          # php artisan
c          # composer
pest       # ./vendor/bin/pest
pint       # ./vendor/bin/pint
fresh      # php artisan migrate:fresh --seed
vphp83     # valet use php@8.3
```

### Git
```bash
gs         # git status
gp         # git push
gl         # git pull
gcb        # git checkout -b
glog       # pretty git log
```

### Modern CLI
```bash
ls         # eza --icons
ll         # eza -la --icons --git
cat        # bat
grep       # ripgrep
z          # zoxide (smart cd)
```

## Key Functions

```bash
p              # Run pest or phpunit (auto-detect)
mkd <dir>      # mkdir && cd
clone <repo>   # gh repo clone && cd
fe             # Fuzzy find and edit file
fcd            # Fuzzy cd into directory
db-create      # Create database (DBngin)
db-drop        # Drop database
```

## Updating

Run the update script to update all packages:

```bash
~/.dotfiles/bin/update
```

On Linux, use `bin/install-linux-devstation` and `bin/workstation-sync`; the macOS `install` and `update` scripts retain their macOS/Homebrew role and do not perform Linux package or sudo operations.

This updates:
- Dotfiles repository
- Homebrew packages
- Oh My Zsh
- Global Composer packages
- Node LTS (via FNM)

## Local Overrides

Create `~/.zshrc.local` for machine-specific settings that shouldn't be in the repo:

```bash
# Example: Project-specific aliases
alias myproject="cd ~/Sites/myproject && code ."
```

## Manual Setup Required

Some apps sync via their own accounts and aren't managed here:
- **Warp** - Log in to sync settings
- **Raycast** - Configure manually
- **PhpStorm** - Use JetBrains account sync

## Verification

After installation, verify everything works:

```bash
which zoxide        # Should return path
ls                  # Should show icons (eza)
cat ~/.zshrc        # Should show syntax highlighting (bat)
z                   # Should work for directory jumping
starship --version  # Prompt working
fnm list            # Node versions
php -v              # PHP working
git diff            # Shows delta side-by-side
```

## Credits

Inspired by [freekmurze/dotfiles](https://github.com/freekmurze/dotfiles).
