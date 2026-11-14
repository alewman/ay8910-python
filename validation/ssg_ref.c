/* A headless harness around the SSG block of nukeykt's YM2203-LLE
 * (reference/src/YM2203-LLE, GPL-2.0+, pinned at 817387f), built by
 * validation/build_referees.sh and run as a referee.  Nothing of YM2203-LLE is
 * copied into ay8910-python: this file only drives its pins and reads its three
 * analogue outputs.
 *
 *   ssg_ref <events.bin> <out.bin> <steps> <phase>
 *
 * The YM2203's SSG serves its three tones and its envelope in turn from one
 * counter, so one "step" here is one turn of the four.  The harness first selects
 * prescaler $2F (FM = master / 2, SSG = master / 1), where a turn is four master
 * clocks: the model skips its logic on calls where its FM clocks have not moved,
 * and with the power-on prescaler that leaves the SSG's own divider unclocked.
 *
 * events.bin: little-endian records of {u64 step; u8 register; u8 value}, sorted,
 * at most one to a step.  A record is an address write (A0 = 0) over the high
 * half of one master clock and a data write (A0 = 1) over its low half; the
 * clock is the `phase`th (0-3) of the step the record names.
 *
 * out.bin: per step, sampled at its end, the three outputs as the model gives
 * them: {f32 a; f32 b; f32 c}, each one of the 32 levels of its DAC table.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "fmopn.h"

typedef struct { unsigned long long step; unsigned char reg, value; } event_t;

static fmopn_t chip;

static void strobe(int a0, int data)
{
    chip.input.a0 = a0;
    chip.input.data = data;
    chip.input.cs = 0;
    chip.input.wr = 0;
}

static void release(void)
{
    chip.input.wr = 1;
    chip.input.cs = 1;
}

static void master_clock(void)
{
    FMOPN_Clock(&chip, 1);
    FMOPN_Clock(&chip, 0);
}

int main(int argc, char **argv)
{
    if (argc < 5) {
        fprintf(stderr, "usage: %s events.bin out.bin steps phase\n", argv[0]);
        return 2;
    }
    unsigned long long steps = strtoull(argv[3], NULL, 10);
    int phase = atoi(argv[4]);
    if (phase < 0 || phase > 3) { fprintf(stderr, "phase must be 0-3\n"); return 2; }

    FILE *ef = fopen(argv[1], "rb");
    if (!ef) { perror(argv[1]); return 1; }
    fseek(ef, 0, SEEK_END);
    long count = ftell(ef) / 10;
    fseek(ef, 0, SEEK_SET);
    event_t *events = calloc(count ? count : 1, sizeof(event_t));
    for (long i = 0; i < count; i++) {
        unsigned char rec[10];
        if (fread(rec, 1, 10, ef) != 10) { fprintf(stderr, "short event file\n"); return 1; }
        unsigned long long t = 0;
        for (int b = 7; b >= 0; b--) t = (t << 8) | rec[b];
        events[i].step = t;
        events[i].reg = rec[8];
        events[i].value = rec[9];
    }
    fclose(ef);

    FILE *of = fopen(argv[2], "wb");
    if (!of) { perror(argv[2]); return 1; }
    setvbuf(of, NULL, _IOFBF, 1 << 20);

    memset(&chip, 0, sizeof(chip));
    chip.input.cs = 1;
    chip.input.wr = 1;
    chip.input.rd = 1;
    chip.input.gpio_a = 255;
    chip.input.gpio_b = 255;
    chip.input.ic = 0;                      /* /IC low: reset */
    for (int i = 0; i < 256; i++) master_clock();
    chip.input.ic = 1;
    strobe(0, 0x2f);                        /* the prescaler: an address write alone */
    for (int i = 0; i < 8; i++) master_clock();
    release();
    for (int i = 0; i < 64; i++) master_clock();

    long next = 0;
    for (unsigned long long step = 0; step < steps; step++) {
        int writing = next < count && events[next].step <= step;
        if (writing && next + 1 < count && events[next + 1].step <= step) {
            fprintf(stderr, "two events in step %llu\n", step);
            return 1;
        }
        for (int m = 0; m < 4; m++) {
            if (writing && m == phase) {
                strobe(0, events[next].reg);
                FMOPN_Clock(&chip, 1);
                release();
                strobe(1, events[next].value);
                FMOPN_Clock(&chip, 0);
                release();
            } else {
                master_clock();
            }
        }
        next += writing;
        float out[3] = { chip.o_analog_a, chip.o_analog_b, chip.o_analog_c };
        fwrite(out, sizeof(float), 3, of);
    }
    fclose(of);
    free(events);
    return 0;
}
