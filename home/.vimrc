" ─────────────────────────────────────────────────────────────────────
" Basic Settings
" ─────────────────────────────────────────────────────────────────────
set nocompatible              " Use Vim settings, not Vi
syntax enable                 " Enable syntax highlighting
filetype plugin indent on     " Enable filetype detection

" ─────────────────────────────────────────────────────────────────────
" Editor Appearance
" ─────────────────────────────────────────────────────────────────────
set number                    " Show line numbers
set relativenumber            " Relative line numbers
set cursorline                " Highlight current line
set showmatch                 " Highlight matching brackets
set showcmd                   " Show command in bottom bar
set laststatus=2              " Always show status line
set ruler                     " Show cursor position
set title                     " Set terminal title
set scrolloff=8               " Keep 8 lines above/below cursor

" Colors
set background=dark
colorscheme desert

" ─────────────────────────────────────────────────────────────────────
" Indentation
" ─────────────────────────────────────────────────────────────────────
set tabstop=4                 " Tab = 4 spaces
set softtabstop=4             " Tab in insert mode = 4 spaces
set shiftwidth=4              " Indent = 4 spaces
set expandtab                 " Use spaces instead of tabs
set autoindent                " Copy indent from current line
set smartindent               " Smart autoindenting

" ─────────────────────────────────────────────────────────────────────
" Search
" ─────────────────────────────────────────────────────────────────────
set incsearch                 " Search as you type
set hlsearch                  " Highlight search results
set ignorecase                " Case insensitive search
set smartcase                 " Case sensitive if uppercase used

" Clear search highlighting with Escape
nnoremap <Esc> :nohlsearch<CR>

" ─────────────────────────────────────────────────────────────────────
" Behavior
" ─────────────────────────────────────────────────────────────────────
set backspace=indent,eol,start  " Better backspace behavior
set hidden                    " Allow switching buffers without saving
set mouse=a                   " Enable mouse support
set clipboard=unnamed         " Use system clipboard
set wildmenu                  " Visual autocomplete for commands
set wildmode=list:longest     " Tab completion
set autoread                  " Reload files changed outside vim
set encoding=utf-8            " UTF-8 encoding
set fileencoding=utf-8

" ─────────────────────────────────────────────────────────────────────
" Backups & Undo
" ─────────────────────────────────────────────────────────────────────
set nobackup                  " Don't create backup files
set nowritebackup
set noswapfile                " Don't create swap files
set undofile                  " Persistent undo
set undodir=~/.vim/undo       " Undo file location

" Create undo directory if it doesn't exist
if !isdirectory(expand("~/.vim/undo"))
    call mkdir(expand("~/.vim/undo"), "p")
endif

" ─────────────────────────────────────────────────────────────────────
" Key Mappings
" ─────────────────────────────────────────────────────────────────────
" Leader key
let mapleader = ","

" Quick save
nnoremap <leader>w :w<CR>

" Quick quit
nnoremap <leader>q :q<CR>

" Move between splits
nnoremap <C-h> <C-w>h
nnoremap <C-j> <C-w>j
nnoremap <C-k> <C-w>k
nnoremap <C-l> <C-w>l

" Move lines up/down
nnoremap <A-j> :m .+1<CR>==
nnoremap <A-k> :m .-2<CR>==

" Better indentation in visual mode
vnoremap < <gv
vnoremap > >gv

" ─────────────────────────────────────────────────────────────────────
" File Type Specific
" ─────────────────────────────────────────────────────────────────────
autocmd FileType php setlocal tabstop=4 shiftwidth=4
autocmd FileType javascript setlocal tabstop=2 shiftwidth=2
autocmd FileType typescript setlocal tabstop=2 shiftwidth=2
autocmd FileType json setlocal tabstop=2 shiftwidth=2
autocmd FileType yaml setlocal tabstop=2 shiftwidth=2
autocmd FileType html setlocal tabstop=2 shiftwidth=2
autocmd FileType css setlocal tabstop=2 shiftwidth=2
autocmd FileType vue setlocal tabstop=2 shiftwidth=2

" Blade files
autocmd BufRead,BufNewFile *.blade.php set filetype=blade
