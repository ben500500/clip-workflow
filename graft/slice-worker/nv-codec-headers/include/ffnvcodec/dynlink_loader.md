# slice-worker/nv-codec-headers/include/ffnvcodec/dynlink_loader.h

- CudaFunctions · class · L138-L244 — typedef struct CudaFunctions
- CudaFunctions · type · L246-L246 — typedef struct CudaFunctions CudaFunctions;
- CuvidFunctions · class · L249-L277 — typedef struct CuvidFunctions
- NVENCAPI · type · L279-L279 — typedef NVENCSTATUS NVENCAPI tNvEncodeAPICreateInstance(NV_ENCODE_API_FUNCTION_LIST *functionList);
- NVENCAPI · type · L280-L280 — typedef NVENCSTATUS NVENCAPI tNvEncodeAPIGetMaxSupportedVersion(uint32_t* version);
- NvencFunctions · class · L282-L287 — typedef struct NvencFunctions
- cuda_free_functions · function · L290-L293 — static inline void cuda_free_functions(CudaFunctions **functions)
- cuvid_free_functions · function · L296-L299 — static inline void cuvid_free_functions(CuvidFunctions **functions)
- nvenc_free_functions · function · L301-L304 — static inline void nvenc_free_functions(NvencFunctions **functions)
- cuda_load_functions · function · L307-L415 — static inline int cuda_load_functions(CudaFunctions **functions, void *logctx)
- cuvid_load_functions · function · L418-L454 — static inline int cuvid_load_functions(CuvidFunctions **functions, void *logctx)
- nvenc_load_functions · function · L456-L464 — static inline int nvenc_load_functions(NvencFunctions **functions, void *logctx)
