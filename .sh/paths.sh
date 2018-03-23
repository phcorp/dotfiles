#!/bin/bash

# default paths
export PATH=/usr/local/sbin:$PATH;
export PATH=./bin:$PATH;

# user
export PATH=$HOME/.bin:$PATH;

# nvm
export NVM_DIR="$HOME/.nvm"
. "/usr/local/opt/nvm/nvm.sh"

# nodenv
eval "$(nodenv init -)";
export PATH=$HOME/node_modules/.bin:$PATH;
export PATH=./node_modules/.bin:$PATH;

# golang
export GOPATH=$HOME/golang
export GOROOT=/usr/local/opt/go/libexec
export PATH=$PATH:$GOPATH/bin
export PATH=$PATH:$GOROOT/bin

# composer
export PATH=$HOME/.composer/bin:$PATH;
export PATH=./vendor/bin:$PATH;

# tools
export PATH=/usr/local/opt/gettext/bin:$PATH
