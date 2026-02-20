# ─────────────────────────────────────────────────────────────────────
# Oh My Zsh Configuration
# ─────────────────────────────────────────────────────────────────────
export ZSH="$HOME/.oh-my-zsh"

# Theme (disabled - using Starship instead)
ZSH_THEME=""

# Plugins
plugins=(
    git
    docker
)

# Load Oh My Zsh
source $ZSH/oh-my-zsh.sh

# ─────────────────────────────────────────────────────────────────────
# Homebrew (Apple Silicon)
# ─────────────────────────────────────────────────────────────────────
if [[ $(uname -m) == "arm64" ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
fi

# ─────────────────────────────────────────────────────────────────────
# Path Configuration
# ─────────────────────────────────────────────────────────────────────
# Composer global bin
export PATH="$HOME/.composer/vendor/bin:$PATH"

# Dotfiles bin
export PATH="$HOME/.dotfiles/bin:$PATH"

# ─────────────────────────────────────────────────────────────────────
# Source Custom Files
# ─────────────────────────────────────────────────────────────────────
[[ -f ~/.exports ]] && source ~/.exports
[[ -f ~/.aliases ]] && source ~/.aliases
[[ -f ~/.functions ]] && source ~/.functions

# Local overrides (not in dotfiles repo)
[[ -f ~/.zshrc.local ]] && source ~/.zshrc.local

# ─────────────────────────────────────────────────────────────────────
# FNM (Fast Node Manager)
# ─────────────────────────────────────────────────────────────────────
if command -v fnm &>/dev/null; then
    eval "$(fnm env --use-on-cd)"
fi

# ─────────────────────────────────────────────────────────────────────
# Zoxide (Smart cd)
# ─────────────────────────────────────────────────────────────────────
if command -v zoxide &>/dev/null; then
    eval "$(zoxide init zsh)"
fi

# ─────────────────────────────────────────────────────────────────────
# Direnv (Per-project environment)
# ─────────────────────────────────────────────────────────────────────
if command -v direnv &>/dev/null; then
    eval "$(direnv hook zsh)"
fi

# ─────────────────────────────────────────────────────────────────────
# FZF
# ─────────────────────────────────────────────────────────────────────
[[ -f ~/.fzf.zsh ]] && source ~/.fzf.zsh

# ─────────────────────────────────────────────────────────────────────
# Zsh Plugins (from Homebrew)
# ─────────────────────────────────────────────────────────────────────
# Autosuggestions
if [[ -f $(brew --prefix)/share/zsh-autosuggestions/zsh-autosuggestions.zsh ]]; then
    source $(brew --prefix)/share/zsh-autosuggestions/zsh-autosuggestions.zsh
fi

# Completions
if type brew &>/dev/null; then
    FPATH="$(brew --prefix)/share/zsh-completions:$FPATH"
    autoload -Uz compinit
    compinit
fi

# ─────────────────────────────────────────────────────────────────────
# SSH Agent
# ─────────────────────────────────────────────────────────────────────
# Add SSH key to agent (macOS Keychain)
ssh-add --apple-use-keychain ~/.ssh/id_ed25519 2>/dev/null

# ─────────────────────────────────────────────────────────────────────
# Starship Prompt (must be last)
# ─────────────────────────────────────────────────────────────────────
if command -v starship &>/dev/null; then
    eval "$(starship init zsh)"
fi
