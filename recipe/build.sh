#!/usr/bin/env bash

set -ex

# sed -i option is handled differently in Linux and OSX
if [ $(uname) == Darwin ]; then
    INPLACE_SED="sed -i \"\" -e"
else
    INPLACE_SED="sed -i"
fi

# conda build cannot find boost libraries from
# ThirdParty/lib. Actually, moving environment boost libraries to
# ThirdParty/lib does not make much sense. The following is just a
# quick workaround of the problem. Upstream will remove the relevant
# code from CMakeLists.txt as not needed.
$INPLACE_SED 's:DESTINATION ThirdParty/lib:DESTINATION lib:g' CMakeLists.txt

export LDFLAGS="-L$PREFIX/lib -Wl,-rpath,$PREFIX/lib"

# Enforce PREFIX instead of BUILD_PREFIX:
export ZLIB_ROOT=$PREFIX
export LibArchive_ROOT=$PREFIX
export Curses_ROOT=$PREFIX
export Glog_ROOT=$PREFIX
export Snappy_ROOT=$PREFIX
export Boost_ROOT=$PREFIX
export PNG_ROOT=$PREFIX
export GDAL_ROOT=$PREFIX

# Make sure -fPIC is not in CXXFLAGS (that some conda packages may
# add):
export CXXFLAGS="`echo $CXXFLAGS | sed 's/-fPIC//'`"

# go overwrites CC and CXX with nonsense (see
# https://github.com/conda-forge/go-feedstock/issues/47), hence we
# redefine these below. Reset GO env variables for omniscidb build
# (IIRC, it is needed for CUDA support):
#export CGO_ENABLED=1
#export CGO_LDFLAGS=
#export CGO_CFLAGS=$CFLAGS
#export CGO_CPPFLAGS=

# Adjust OPENSSL_ROOT for conda environment. This ensures that
# openssl is picked up from host environment:
$INPLACE_SED 's!/usr/local/opt/openssl!\'$PREFIX'!g' CMakeLists.txt

# Avoid picking up boost/regexp header files from system if there:
$INPLACE_SED 's!/usr/local!\'$PREFIX'!g' CMakeLists.txt

if [ $(uname) == Darwin ]; then
    # Darwin has only clang, must use clang++ from clangdev
    export CC=$PREFIX/bin/clang
    export CXX=$PREFIX/bin/clang++
    export CMAKE_CC=$PREFIX/bin/clang
    export CMAKE_CXX=$PREFIX/bin/clang++

    # Adding `--sysroot=...` resolves `no member named 'signbit' in the global namespace` error:
    # Adding `-I$BUILD_SYSROOT_INLCUDE` resolves `assert.h file not found` error:
    $INPLACE_SED 's!ARGS -std=c++14!ARGS -std=c++14 --sysroot=\'$CONDA_BUILD_SYSROOT' -I\'$CONDA_BUILD_SYSROOT/usr/include'!g' QueryEngine/CMakeLists.txt
    
    # Force ncurses from conda host environment (enable when needed):
    #$INPLACE_SED 's/find_package(Curses REQUIRED)/set(CURSES_NEED_NCURSES TRUE)\'$'\nfind_package(Curses REQUIRED)/g' CMakeLists.txt

    # Make sure that llvm-config and clang++ are from host
    # environment, otherwise the build environment contains
    # clang/llvm-4.0.1 that will interfer badly with llvmdev/clangdev
    # in the host environment:
    export PATH=$PREFIX/bin:$PATH
else
    # Linux
    echo "uname=${uname}"
    # must use gcc compiler as llvmdev is built with gcc and there
    # exists ABI incompatibility between llvmdev-7 built with gcc and
    # clang.
    COMPILERNAME=clang                      # options: clang, gcc

    if [ "$COMPILERNAME" == "clang" ]; then
        export CC=$PREFIX/bin/clang
        export CXX=$PREFIX/bin/clang++
        export CMAKE_CC=$PREFIX/bin/clang
        export CMAKE_CXX=$PREFIX/bin/clang++

        # Resolves `It appears that you have Arrow < 0.10.0`:
        export CFLAGS="$CFLAGS -pthread"
        export LDFLAGS="$LDFLAGS -lpthread -lrt -lresolv"
    else
        GXX=$BUILD_PREFIX/bin/$HOST-g++         # replace with $GXX
        GCCSYSROOT=$BUILD_PREFIX/$HOST/sysroot
        GCCVERSION=$(basename $(dirname $($GXX -print-libgcc-file-name)))
        GXXINCLUDEDIR=$BUILD_PREFIX/$HOST/include/c++/$GCCVERSION
        GCCLIBDIR=$BUILD_PREFIX/lib/gcc/$HOST/$GCCVERSION

        export CC=$PREFIX/bin/clang
        export CXX=  # not used
        export CMAKE_CC=$PREFIX/bin/$HOST-gcc
        export CMAKE_CXX=$PREFIX/bin/$HOST-g++

        # Add gcc include directory to astparser, resolves `not found
        # include file`: cstdint
        # TODO: recheck its need as on Ubuntu 18.04 tests pass without this patch
        $INPLACE_SED 's!arg_vector\[3\] = {arg0, arg1!arg_vector\[4\] = {arg0, arg1, "-extra-arg=-I'$GXXINCLUDEDIR'"!g' QueryEngine/UDFCompiler.cpp
    fi

    # fixes `undefined reference to
    # `boost::system::detail::system_category_instance'`:
    export CXXFLAGS="$CXXFLAGS -DBOOST_ERROR_CODE_HEADER_ONLY"

    # make sure that $LD is always used as a linker:
    cp -v $LD $BUILD_PREFIX/bin/ld
fi

export CMAKE_COMPILERS="-DCMAKE_C_COMPILER=$CMAKE_CC -DCMAKE_CXX_COMPILER=$CMAKE_CXX"

mkdir -p build
cd build

cmake -Wno-dev \
    -DCMAKE_INSTALL_PREFIX=$PREFIX \
    -DCMAKE_BUILD_TYPE=release \
    -DMAPD_DOCS_DOWNLOAD=off \
    -DENABLE_AWS_S3=off \
    -DENABLE_CUDA=off \
    -DENABLE_FOLLY=off \
    -DENABLE_JAVA_REMOTE_DEBUG=off \
    -DENABLE_PROFILER=off \
    -DENABLE_TESTS=on  \
    -DPREFER_STATIC_LIBS=off \
    $CMAKE_COMPILERS \
    ..

make -j $CPU_COUNT
make install

mkdir tmp
$PREFIX/bin/initdb tmp
make sanity_tests
rm -rf tmp

# copy initdb to mapd_initdb to avoid conflict with psql initdb
cp $PREFIX/bin/initdb $PREFIX/bin/omnisci_initdb
