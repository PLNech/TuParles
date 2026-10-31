/* TuParles.app entry. Embedding Python here keeps the process inside this
 * bundle, so the menu-bar icon and the Accessibility prompt belong to
 * TuParles. A shell that execs Homebrew's interpreter is attributed to
 * Python.app, and that status item lands off-screen. */
#include <Python.h>
#include <libgen.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <mach-o/dyld.h>

static void exe_dir(char *out, size_t n) {
    uint32_t size = (uint32_t)n;
    if (_NSGetExecutablePath(out, &size) != 0) {
        fprintf(stderr, "TuParles: executable path too long\n");
        exit(1);
    }
    char *slash = strrchr(out, '/');
    if (slash) {
        *slash = '\0';
    }
}

int main(int argc, char **argv) {
    char exe[4096];
    exe_dir(exe, sizeof exe);

    char boot[4096];
    snprintf(boot, sizeof boot, "%s/../Resources/tuparles-boot.py", exe);

    wchar_t *program = Py_DecodeLocale(argv[0], NULL);
    if (!program) {
        fprintf(stderr, "TuParles: cannot decode argv0\n");
        return 1;
    }
    Py_SetProgramName(program);
    Py_Initialize();

    FILE *fp = fopen(boot, "r");
    if (!fp) {
        fprintf(stderr, "TuParles: missing %s\n", boot);
        return 1;
    }
    int rc = PyRun_SimpleFileEx(fp, boot, 1);
    if (Py_FinalizeEx() < 0) {
        return 120;
    }
    PyMem_RawFree(program);
    return rc == 0 ? 0 : 1;
}
