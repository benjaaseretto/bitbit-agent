# Flujos complejos adaptados (sanatorio / venta equipos)

Cada fila tiene **spec** + **KB** (`app/kb/complex/<flow_key>.json`).
Patrón estructural de colly-agent; marcas y textos reescritos.

```bash
BITBIT_FLOW_KEY=aurora_salud_flow python -m app.pipecat_runtime.bot --transport webrtc
```

| # | flow_key | Vertical | Nodos | KB | Patrón |
|---|----------|----------|------:|---:|--------|
| 1 | `aurora_salud_flow` | sanatorio | 58 | 38 | `caja_los_andes_repro_transunion_flow.json` |
| 2 | `norte_vital_flow` | sanatorio | 56 | 38 | `caja_los_andes_reprogramaciones_flow.json` |
| 3 | `pacifico_med_flow` | sanatorio | 49 | 34 | `bravo_co_flow_graph.json` |
| 4 | `andes_care_flow` | sanatorio | 36 | 47 | `calidda_flow_graph.json` |
| 5 | `rio_blanco_flow` | sanatorio | 35 | 30 | `bravo_growth_co_flow_graph.json` |
| 6 | `sol_integral_flow` | sanatorio | 32 | 23 | `cashea_flow_graph.json` |
| 7 | `vita_sur_flow` | sanatorio | 29 | 29 | `bodesa_castigo_flow_graph.json` |
| 8 | `med_plaza_flow` | sanatorio | 28 | 38 | `caja_los_andes_regrabacion_flow.json` |
| 9 | `horizonte_clinico_flow` | sanatorio | 28 | 37 | `bodesa_90_120_flow_graph.json` |
| 10 | `bosque_salud_flow` | sanatorio | 28 | 36 | `bodesa_60_90_flow_graph.json` |
| 11 | `celeste_hospital_flow` | sanatorio | 27 | 39 | `ventipay_flow_graph.json` |
| 12 | `mirador_medico_flow` | sanatorio | 27 | 26 | `bodesa_flow_graph.json` |
| 13 | `laguna_clinica_flow` | sanatorio | 25 | 23 | `abc_flow_graph.json` |
| 14 | `altos_del_sur_flow` | sanatorio | 25 | 23 | `abcdin_externo_flow_graph.json` |
| 15 | `portal_salud_flow` | sanatorio | 24 | 67 | `tenpo_flow_graph.json` |
| 16 | `estrella_medica_flow` | sanatorio | 24 | 30 | `caja_los_andes_colly_flow.json` |
| 17 | `camino_verde_flow` | sanatorio | 24 | 22 | `abcdin_lax_flow_graph.json` |
| 18 | `faro_clinico_flow` | sanatorio | 24 | 13 | `nu_mx_strict_flow_graph.json` |
| 19 | `sierra_vital_flow` | sanatorio | 23 | 39 | `banco_falabella_peru_flow_graph.json` |
| 20 | `costa_salud_flow` | sanatorio | 22 | 20 | `santander_mora_temprana_flow_graph.json` |
| 21 | `nube_blanca_flow` | sanatorio | 21 | 33 | `sanborns_castigo_mora_9_flow_graph.json` |
| 22 | `prisma_med_flow` | sanatorio | 21 | 33 | `belcorp_flow_graph.json` |
| 23 | `valle_cuidado_flow` | sanatorio | 21 | 18 | `unicomer_gt_flow_graph.json` |
| 24 | `origen_salud_flow` | sanatorio | 21 | 51 | `bravo_mx_flow_graph.json` |
| 25 | `lumen_clinica_flow` | sanatorio | 20 | 34 | `sanborns_castigo_mora_456_flow_graph.json` |
| 26 | `tecno_medico_flow` | equipos | 20 | 37 | `kredit_plus_flow_graph.json` |
| 27 | `oxigeno_plus_flow` | equipos | 19 | 52 | `nexu_flow_graph.json` |
| 28 | `labtech_sur_flow` | equipos | 19 | 42 | `mapfre_pe_flow_graph.json` |
| 29 | `imagen_pro_flow` | equipos | 19 | 46 | `mi_banco_co_flow_graph.json` |
| 30 | `quirurgica_nova_flow` | equipos | 19 | 32 | `rapicredit_renegociacion_preventiva_flow_graph.json` |
| 31 | `monitor_vital_flow` | equipos | 19 | 32 | `rapicredit_renegociacion_mora_flow_graph.json` |
| 32 | `steril_pack_flow` | equipos | 19 | 13 | `nu_mx_strict_castigo_flow_graph.json` |
| 33 | `infusion_max_flow` | equipos | 19 | 13 | `nu_mx_interno_strict_castigo_flow_graph.json` |
| 34 | `diagno_lab_flow` | equipos | 18 | 25 | `sicrea_mx_flow_graph.json` |
| 35 | `rehab_motion_flow` | equipos | 18 | 32 | `skandia_co_flow_graph.json` |
| 36 | `dental_core_flow` | equipos | 18 | 31 | `skandia_co_24_flow_graph.json` |
| 37 | `cardio_gear_flow` | equipos | 18 | 38 | `rapicredit_novacion_mora_flow_graph.json` |
| 38 | `neonatal_kit_flow` | equipos | 18 | 38 | `rapicredit_novacion_preventiva_flow_graph.json` |
| 39 | `ultra_scan_flow` | equipos | 18 | 32 | `rapicredit_rapiplazo_novacion_mora_flow_graph.json` |
| 40 | `bio_analyze_flow` | equipos | 18 | 33 | `sanborns_castigo_flow_graph.json` |
| 41 | `or_suite_flow` | equipos | 18 | 16 | `nu_flow_graph.json` |
| 42 | `home_care_tech_flow` | equipos | 18 | 33 | `izzi_flow_graph.json` |
| 43 | `pharmacy_auto_flow` | equipos | 18 | 26 | `bravo_es_vigente_flow_graph.json` |
| 44 | `sterile_flow_flow` | equipos | 18 | 13 | `nu_mx_interno_strict_flow_graph.json` |
| 45 | `pulse_line_flow` | equipos | 17 | 34 | `bancaribe_flow_graph.json` |

## Archivos

- Specs: `app/flow_graph/demo_specs/complex/`
- KB: `app/kb/complex/`

## Runtime

- Implementadas: `IdentityVerificationTask`, `AppointmentSchedulingTask`.
- Resto: `app/tasks/stubs.py` (portar bajo demanda).
