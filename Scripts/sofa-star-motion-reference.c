#include <errno.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "sofa.h"
#include "sofam.h"

static double parse(const char *text) {
    errno = 0;
    char *end = NULL;
    const double value = strtod(text, &end);
    if (errno || !end || *end || !isfinite(value)) exit(65);
    return value;
}

int main(int argc, char **argv) {
    if (argc != 10 && argc != 14) return 64;
    const double ra = parse(argv[1]) * DD2R;
    const double dec = parse(argv[2]) * DD2R;
    const double parallax = parse(argv[3]) / 1000.0;
    const double pmr = parse(argv[4]) * DMAS2R / cos(dec);
    const double pmd = parse(argv[5]) * DMAS2R;
    const double rv = parse(argv[6]);
    const double epoch = parse(argv[7]);
    const double target = parse(argv[8]);
    double targetTCB1, targetTCB2;
    if (!strcmp(argv[9], "full")) {
        iauTdbtcb(DJ00, (target - 2000.0) * DJY, &targetTCB1, &targetTCB2);
    } else if (!strcmp(argv[9], "naive")) {
        targetTCB1 = DJ00;
        targetTCB2 = (target - 2000.0) * DJY;
    } else {
        return 67;
    }
    if (argc == 14) {
        if (strcmp(argv[10], "observer")) return 68;
        double observer[3] = {parse(argv[11]), parse(argv[12]), parse(argv[13])};
        double direction[3];
        const double interval = ((targetTCB1 - DJ00) + targetTCB2 - (epoch - 2000.0) * DJY) / DJY;
        iauPmpx(ra, dec, pmr, pmd, parallax, rv, interval, observer, direction);
        printf("%.17g %.17g %.17g\n", direction[0], direction[1], direction[2]);
        return 0;
    }
    double resultRA, resultDec, resultPMRA, resultPMDec, resultParallax, resultRV;
    const int status = iauPmsafe(
        ra, dec, pmr, pmd, parallax, rv,
        DJ00, (epoch - 2000.0) * DJY,
        targetTCB1, targetTCB2,
        &resultRA, &resultDec, &resultPMRA, &resultPMDec, &resultParallax, &resultRV
    );
    if (status != 0) return 66;
    printf("%.17g %.17g %.17g %.17g %.17g %.17g\n", resultRA, resultDec, resultPMRA, resultPMDec, resultParallax, resultRV);
    return 0;
}
