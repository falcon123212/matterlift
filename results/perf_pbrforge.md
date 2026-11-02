# pbrforge performance (2026-11-02)

Windows 11, AMD64 Family 25 Model 80 Stepping 0, AuthenticAMD, 12 threads, Python 3.12.0, NumPy 2.5.4. Input: 1600x1600 albedo (Muse Image size), stone detail, wear 0.4, metal. Derive is the median of 3 runs (1 at 4K); peak memory is what NumPy allocates during derive.

| Size | Format | Derive (s) | Derive peak (MB) | Export + zip (s) | Zip (MB) |
|---|---|---|---|---|---|
| 512 | PNG | 0.35 | 46 | 0.78 | 6.4 |
| 512 | JPG | 0.35 | 46 | 0.62 | 5.2 |
| 1024 | PNG | 1.32 | 122 | 2.11 | 20.3 |
| 1024 | JPG | 1.32 | 122 | 1.62 | 15.0 |
| 2048 | PNG | 5.46 | 487 | 7.79 | 66.2 |
| 2048 | JPG | 5.46 | 487 | 5.48 | 46.6 |
| 4096 | PNG | 24.71 | 2483 | 31.0 | 223.6 |
| 4096 | JPG | 24.71 | 2483 | 21.19 | 149.2 |
