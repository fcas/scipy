"""
Generate wrappers to dispatch BLAS/LAPACK calls to the properly prefixed/
suffixed symbols.

For example, MacOS 13.3+ has a new, LAPACK 3.9-compatible, high performance
BLAS/LAPACK implementation. These functions are provided side-by-side with
the old implementation, and the symbols are distinguished by appending the
literal suffix "$NEWLAPACK".

To point our BLAS/LAPACK calls to these symbols, we need to create wrappers
which call them appropriately. We do this as simple C function declarations
that make use of the preprocessor macros defined in npy_cblas.h.

We already have all the required signature information in
    scipy/linalg/cython_{blas,lapack}_signatures.txt
which is generated by
    scipy/linalg/_cython_signature_generator.py

We automatically create the declarations based on these signatures, with a
few special cases. First, all complex-valued functions are skipped (empty
source files) because they require more complicated wrapper logic. The
wrappers for these functions are hard-coded in wrap_g77_abi.c and
wrap_dummy_g77_abi.c. Second, certain functions are missing from the
new Accelerate implementation and/or have unusual symbols that require
special handling in this script.
"""
import argparse
import os

from _wrappers_common import (C_PREAMBLE, C_TYPES, CPP_GUARD_BEGIN,
                              CPP_GUARD_END, LAPACK_DECLS, USE_OLD_ACCELERATE,
                              WRAPPED_FUNCS, all_newer,
                              get_blas_macro_and_name, read_signatures,
                              write_files)

CURR_DIR = os.path.dirname(os.path.abspath(__file__))
LINALG_DIR = os.path.abspath(os.path.join(CURR_DIR, "..", "linalg"))
C_COMMENT = f"""/*
This file was generated by {os.path.basename(__file__)}.
Do not edit this file directly.
*/\n\n"""


def generate_decl_wrapper(name, return_type, argnames, argtypes, accelerate):
    """
    Create wrapper function declaration.

    Wrapper has symbol `F_FUNC(name,NAME)` and wraps the BLAS/LAPACK function
    `blas_macro(blas_name)` (by default: `BLAS_FUNC(name)`).
    """
    # Complex-valued functions have hard-coded wrappers in G77 ABI wrappers
    if name in WRAPPED_FUNCS:
        return ""
    # If using standard old Accelerate symbols, no wrapper required
    if accelerate and name in USE_OLD_ACCELERATE:
        return ""
    c_return_type = C_TYPES[return_type]
    c_argtypes = [C_TYPES[t] for t in argtypes]
    param_list = ', '.join(f'{t} *{n}' for t, n in zip(c_argtypes, argnames))
    argnames = ', '.join(argnames)
    blas_macro, blas_name = get_blas_macro_and_name(name, accelerate)
    return f"""
{c_return_type} {blas_macro}({blas_name})({param_list});
{c_return_type} F_FUNC({name},{name.upper()})({param_list}){{
    return {blas_macro}({blas_name})({argnames});
}}
"""


def generate_file_wrapper(sigs, lib_name, accelerate, outdir):
    """
    Returns a dictionary of wrapper file paths to their string contents.
    Each BLAS/LAPACK function gets a separate wrapper file. All wrapper files
    are compiled into an archive that allows the linker to selectively include
    only the necessary symbols for each binary.
    """
    if lib_name == 'BLAS':
        preamble = [C_COMMENT, C_PREAMBLE, CPP_GUARD_BEGIN]
    elif lib_name == 'LAPACK':
        preamble = [C_COMMENT, C_PREAMBLE, LAPACK_DECLS, CPP_GUARD_BEGIN]
    wrappers = {}
    for sig in sigs:
        file_path = os.path.join(outdir, sig["name"] + '.c')
        wrappers[file_path] = ''.join(preamble + [
            generate_decl_wrapper(**sig, accelerate=accelerate), CPP_GUARD_END]
        )
    return wrappers


def make_all(outdir,
             blas_signature_file=os.path.join(
                 LINALG_DIR, "cython_blas_signatures.txt"),
             lapack_signature_file=os.path.join(
                 LINALG_DIR, "cython_lapack_signatures.txt"),
             accelerate=False):
    with open(blas_signature_file) as f:
        blas_sigs = f.readlines()
    with open(lapack_signature_file) as f:
        lapack_sigs = f.readlines()
    blas_sigs = read_signatures(blas_sigs)
    lapack_sigs = read_signatures(lapack_sigs)
    # Do not create new files if not necessary
    src_files = (os.path.abspath(__file__),
                 blas_signature_file,
                 lapack_signature_file)
    dst_files = [os.path.join(outdir, f'{sig["name"]}.c')
                 for sig in blas_sigs + lapack_sigs]
    if all_newer(dst_files, src_files):
        print("scipy/_build_utils/_generate_blas_wrapper.py: all files up-to-date")
        return
    blas_wrappers = generate_file_wrapper(
        blas_sigs, 'BLAS', accelerate, outdir)
    lapack_wrappers = generate_file_wrapper(
        lapack_sigs, 'LAPACK', accelerate, outdir)
    to_write = dict(**blas_wrappers, **lapack_wrappers)
    write_files(to_write)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-o", "--outdir", type=str,
                        help="Path to the output directory")
    parser.add_argument("-a", "--accelerate", action="store_true",
                        help="Whether to use new Accelerate (macOS 13.3+)")
    args = parser.parse_args()

    if not args.outdir:
        outdir_abs = os.path.abspath(os.path.dirname(__file__))
    else:
        outdir_abs = os.path.join(os.getcwd(), args.outdir)

    make_all(outdir_abs, accelerate=args.accelerate)
