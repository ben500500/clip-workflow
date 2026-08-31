---
name: frontend API layer
slug: frontend-api-layer
type: system
sources:
  - path: frontend/src/api/auth.ts
    hash: ca0de968f895916fb29ddf57cb08544d07363771a2740266bc61c939dd71996e
  - path: frontend/src/api/autoclip.ts
    hash: b616fb808862c6a16d14781632bd75a57529de170c842f7c47cff8966aad552b
  - path: frontend/src/api/batchSlice.ts
    hash: 12795f62d80df08b2ad232f28eea023ef9b1afada51aa380fc5d332796b5b345
  - path: frontend/src/api/channelAccounts.ts
    hash: b7f94536d871ab286ec453b6b89b3d198a105ebd76ad122b5fb802dbd8abffdc
  - path: frontend/src/api/client.ts
    hash: 7482c1731330ddc31b68a4f635e589f5177852e379bb711d4242a41d3558ffda
  - path: frontend/src/api/config.ts
    hash: 866c376628366f4ab25682a7f9135cdcbc3dc846a03d3bc2eabcb3b162c52e71
  - path: frontend/src/api/dashboard.ts
    hash: e325735856e558dc9c1d231c293b6a585d604251045cf2bc4605835a765105d0
  - path: frontend/src/api/dramas.ts
    hash: 4e3f7d2340d487c6658393ccb49d24dd07caa3fac07d4ead4769709ac6c9ad94
  - path: frontend/src/api/intervals.ts
    hash: 43d318e9bef45719a0fdbee4214417233c90c6e4ace5eeae31bf6af69bfacfdc
  - path: frontend/src/api/monitor.ts
    hash: 628815c67be7a59df6bcbdbaec1c85d80d4615b217cf1e03d290c41927cfd256
  - path: frontend/src/api/preview.ts
    hash: 6fd48ecc0b768458f8f6ccb22f6667fe05724209e72e2be37d0cbaf2c6654566
  - path: frontend/src/api/projects.ts
    hash: 1d8df540b4e44e9bed66757f30fcd7868b508c1058095372c1ca7e3102ff798a
  - path: frontend/src/api/publish.ts
    hash: 21cf83158d76f1190c5aaae178f57263d21356eca002801e2dd04c0f0fe61d21
  - path: frontend/src/api/publishMaterial.ts
    hash: 13c3229dda5234a8ddd02bc323564d4e838169b08be5d24a8374041f104f3b20
  - path: frontend/src/api/shortdrama.ts
    hash: e1ba066c23ce7b9dd91b97bcc30db5e6bf1d273d14bf08c429e2d12ab9e57a8a
  - path: frontend/src/api/slice.ts
    hash: 34be03907aba862382c7b9a4cd9e88864e5807b9fc6e9da4ff361034220124aa
  - path: frontend/src/api/upload.ts
    hash: d4c4a413919f98d86e3a8412151c2cc21113045bbe1f410915e734955c9a79dd
  - path: frontend/src/api/variants.ts
    hash: d687ac4a047e6e71dbf6c454377bcc4e637fd5a11e2aed6218744b0dd1bccbca
  - path: frontend/src/api/watermark.ts
    hash: 1ddd3038fc2c84890265e6769449e7e0dcf92f2b32d75ddc8dbb4dee16780fd6
  - path: frontend/src/api/wechatDl.ts
    hash: a3bce5c6f69c697e5f227c261fc7ba2f0ea7d33aab1876eedd98cb9c49348e60
sources_digest: 76f399c501bf777d3812b0618971c731a17e45f1f0dd3c628ffbf750a3c3df2e
links:
  - to: dedupe-config-contract
    relation: configures
    description: >-
      sliceApi.run accepts the manual dedupe config produced by
      DedupeManualConfig.
  - to: frontend-auth-session
    relation: part_of
    description: >-
      client.ts's silent refresh flow and auth.ts's cookie-based
      login/refresh/logout are the transport for AuthContext.
generator:
  version: 1
covers:
  - symbol: BatchEpisodeItem
    kind: interface
    at: 'frontend/src/api/batchSlice.ts:L4-L7'
  - symbol: BatchSliceRunRequest
    kind: interface
    at: 'frontend/src/api/batchSlice.ts:L9-L14'
  - symbol: BatchSliceRunResponse
    kind: interface
    at: 'frontend/src/api/batchSlice.ts:L16-L20'
  - symbol: BatchSliceItem
    kind: interface
    at: 'frontend/src/api/batchSlice.ts:L22-L39'
  - symbol: BatchSlice
    kind: interface
    at: 'frontend/src/api/batchSlice.ts:L41-L55'
  - symbol: BatchSliceOutputItem
    kind: interface
    at: 'frontend/src/api/batchSlice.ts:L57-L64'
  - symbol: BatchSliceOutputResponse
    kind: interface
    at: 'frontend/src/api/batchSlice.ts:L66-L69'
  - symbol: ChannelAccountInput
    kind: interface
    at: 'frontend/src/api/channelAccounts.ts:L4-L17'
  - symbol: ChannelAccountFromVideoAccountInput
    kind: interface
    at: 'frontend/src/api/channelAccounts.ts:L19-L29'
  - symbol: OperatorInput
    kind: interface
    at: 'frontend/src/api/channelAccounts.ts:L31-L35'
  - symbol: refreshAccessToken
    kind: function
    at: 'frontend/src/api/client.ts:L27-L39'
  - symbol: Drama
    kind: interface
    at: 'frontend/src/api/dramas.ts:L5-L30'
  - symbol: DramaDetail
    kind: interface
    at: 'frontend/src/api/dramas.ts:L32-L38'
  - symbol: DramaStill
    kind: interface
    at: 'frontend/src/api/dramas.ts:L40-L45'
  - symbol: DramaCreateParams
    kind: interface
    at: 'frontend/src/api/dramas.ts:L47-L65'
  - symbol: DramaUpdateParams
    kind: interface
    at: 'frontend/src/api/dramas.ts:L67-L84'
  - symbol: DramaImportRow
    kind: interface
    at: 'frontend/src/api/dramas.ts:L86-L99'
  - symbol: DramaImportPreviewResult
    kind: interface
    at: 'frontend/src/api/dramas.ts:L101-L107'
  - symbol: DramaImportConfirmItem
    kind: interface
    at: 'frontend/src/api/dramas.ts:L109-L124'
  - symbol: DramaPublishContext
    kind: interface
    at: 'frontend/src/api/dramas.ts:L126-L134'
  - symbol: TopicPreset
    kind: interface
    at: 'frontend/src/api/dramas.ts:L138-L143'
  - symbol: TopicPresetsResult
    kind: interface
    at: 'frontend/src/api/dramas.ts:L145-L149'
  - symbol: getTopicPresets
    kind: function
    at: 'frontend/src/api/dramas.ts:L154-L156'
  - symbol: listDramas
    kind: function
    at: 'frontend/src/api/dramas.ts:L158-L167'
  - symbol: getDrama
    kind: function
    at: 'frontend/src/api/dramas.ts:L169-L171'
  - symbol: createDrama
    kind: function
    at: 'frontend/src/api/dramas.ts:L173-L175'
  - symbol: updateDrama
    kind: function
    at: 'frontend/src/api/dramas.ts:L177-L179'
  - symbol: deleteDrama
    kind: function
    at: 'frontend/src/api/dramas.ts:L180-L182'
  - symbol: feishuImportDrama
    kind: function
    at: 'frontend/src/api/dramas.ts:L185-L194'
  - symbol: uploadDramaImage
    kind: function
    at: 'frontend/src/api/dramas.ts:L198-L211'
  - symbol: addDramaStill
    kind: function
    at: 'frontend/src/api/dramas.ts:L213-L215'
  - symbol: deleteDramaStill
    kind: function
    at: 'frontend/src/api/dramas.ts:L217-L219'
  - symbol: linkDramaAccounts
    kind: function
    at: 'frontend/src/api/dramas.ts:L222-L224'
  - symbol: dramaImportParse
    kind: function
    at: 'frontend/src/api/dramas.ts:L227-L245'
  - symbol: dramaImportPreview
    kind: function
    at: 'frontend/src/api/dramas.ts:L247-L249'
  - symbol: dramaImportConfirm
    kind: function
    at: 'frontend/src/api/dramas.ts:L251-L261'
  - symbol: getDramaPublishContext
    kind: function
    at: 'frontend/src/api/dramas.ts:L264-L266'
  - symbol: linkDramaMaterial
    kind: function
    at: 'frontend/src/api/dramas.ts:L268-L274'
  - symbol: DramaEpisodeStage
    kind: interface
    at: 'frontend/src/api/dramas.ts:L279-L286'
  - symbol: DramaSliceEpisode
    kind: interface
    at: 'frontend/src/api/dramas.ts:L288-L301'
  - symbol: DramaSliceStatus
    kind: interface
    at: 'frontend/src/api/dramas.ts:L303-L312'
  - symbol: linkDramaEpisodes
    kind: function
    at: 'frontend/src/api/dramas.ts:L315-L317'
  - symbol: getDramaSliceStatus
    kind: function
    at: 'frontend/src/api/dramas.ts:L320-L322'
  - symbol: ProjectListParams
    kind: interface
    at: 'frontend/src/api/projects.ts:L4-L9'
  - symbol: ProjectOutputItem
    kind: interface
    at: 'frontend/src/api/projects.ts:L53-L69'
  - symbol: PublishTaskCreate
    kind: interface
    at: 'frontend/src/api/publish.ts:L4-L22'
  - symbol: PublishTaskScheduleInput
    kind: interface
    at: 'frontend/src/api/publish.ts:L24-L29'
  - symbol: PublishTimeSlotInput
    kind: interface
    at: 'frontend/src/api/publish.ts:L31-L36'
  - symbol: VideoAccountInput
    kind: interface
    at: 'frontend/src/api/publish.ts:L38-L51'
  - symbol: PublishTaskAssignInput
    kind: interface
    at: 'frontend/src/api/publish.ts:L53-L64'
  - symbol: MiniProgramInput
    kind: interface
    at: 'frontend/src/api/publish.ts:L66-L73'
  - symbol: PublishMaterial
    kind: interface
    at: 'frontend/src/api/publishMaterial.ts:L4-L13'
  - symbol: PublishMaterialRecord
    kind: interface
    at: 'frontend/src/api/publishMaterial.ts:L15-L27'
  - symbol: PublishMaterialGenerateParams
    kind: interface
    at: 'frontend/src/api/publishMaterial.ts:L29-L38'
  - symbol: PublishMaterialGenerateFromOutputParams
    kind: interface
    at: 'frontend/src/api/publishMaterial.ts:L40-L47'
  - symbol: ShortdramaPromptRecord
    kind: interface
    at: 'frontend/src/api/shortdrama.ts:L3-L45'
  - symbol: DoubaoRewriteItem
    kind: interface
    at: 'frontend/src/api/shortdrama.ts:L47-L54'
  - symbol: DoubaoGenerateParams
    kind: interface
    at: 'frontend/src/api/shortdrama.ts:L56-L59'
  - symbol: DoubaoGenerateResult
    kind: interface
    at: 'frontend/src/api/shortdrama.ts:L61-L65'
  - symbol: SeedanceGenerateResult
    kind: interface
    at: 'frontend/src/api/shortdrama.ts:L67-L71'
  - symbol: PromptGenerateParams
    kind: interface
    at: 'frontend/src/api/shortdrama.ts:L73-L83'
  - symbol: PromptGenerateResult
    kind: interface
    at: 'frontend/src/api/shortdrama.ts:L85-L96'
  - symbol: PromptTemplates
    kind: interface
    at: 'frontend/src/api/shortdrama.ts:L98-L102'
  - symbol: ScriptOptimizeParams
    kind: interface
    at: 'frontend/src/api/shortdrama.ts:L104-L109'
  - symbol: ScriptOptimizeResult
    kind: interface
    at: 'frontend/src/api/shortdrama.ts:L111-L115'
  - symbol: BadgeItem
    kind: interface
    at: 'frontend/src/api/slice.ts:L4-L10'
  - symbol: BadgeUploadResult
    kind: interface
    at: 'frontend/src/api/slice.ts:L12-L17'
  - symbol: TextOverlayItem
    kind: interface
    at: 'frontend/src/api/slice.ts:L20-L28'
  - symbol: SubtitleUploadResult
    kind: interface
    at: 'frontend/src/api/slice.ts:L30-L35'
  - symbol: VariantFingerprint
    kind: interface
    at: 'frontend/src/api/variants.ts:L3-L7'
  - symbol: VariantMatrixItem
    kind: interface
    at: 'frontend/src/api/variants.ts:L9-L26'
  - symbol: VariantGroup
    kind: interface
    at: 'frontend/src/api/variants.ts:L28-L34'
  - symbol: VariantMatrix
    kind: interface
    at: 'frontend/src/api/variants.ts:L36-L39'
  - symbol: VariantDetail
    kind: interface
    at: 'frontend/src/api/variants.ts:L41-L45'
  - symbol: VariantVerifyResult
    kind: interface
    at: 'frontend/src/api/variants.ts:L47-L51'
  - symbol: SliceOutputListItem
    kind: interface
    at: 'frontend/src/api/variants.ts:L53-L64'
  - symbol: SliceOutputEpisode
    kind: interface
    at: 'frontend/src/api/variants.ts:L66-L71'
  - symbol: SliceOutputProject
    kind: interface
    at: 'frontend/src/api/variants.ts:L73-L77'
  - symbol: SliceOutputList
    kind: interface
    at: 'frontend/src/api/variants.ts:L79-L84'
  - symbol: WatermarkVideoItem
    kind: interface
    at: 'frontend/src/api/watermark.ts:L3-L19'
  - symbol: WatermarkTaskItem
    kind: interface
    at: 'frontend/src/api/watermark.ts:L21-L38'
  - symbol: WatermarkTaskDetail
    kind: interface
    at: 'frontend/src/api/watermark.ts:L40-L42'
  - symbol: WatermarkUploadResult
    kind: interface
    at: 'frontend/src/api/watermark.ts:L44-L49'
  - symbol: WatermarkRunParams
    kind: interface
    at: 'frontend/src/api/watermark.ts:L51-L71'
  - symbol: WechatDlTask
    kind: interface
    at: 'frontend/src/api/wechatDl.ts:L3-L20'
  - symbol: WechatDlTaskList
    kind: interface
    at: 'frontend/src/api/wechatDl.ts:L22-L25'
  - symbol: WechatDlImportResult
    kind: interface
    at: 'frontend/src/api/wechatDl.ts:L27-L33'
  - symbol: WechatDlBatchImportResult
    kind: interface
    at: 'frontend/src/api/wechatDl.ts:L35-L41'
  - symbol: WechatDlImportInput
    kind: interface
    at: 'frontend/src/api/wechatDl.ts:L43-L48'
  - symbol: WechatDlImportToProjectInput
    kind: interface
    at: 'frontend/src/api/wechatDl.ts:L50-L54'
  - symbol: WechatDlImportToProjectResult
    kind: interface
    at: 'frontend/src/api/wechatDl.ts:L56-L60'
  - symbol: WechatDlProviderInfo
    kind: interface
    at: 'frontend/src/api/wechatDl.ts:L62-L71'
---
<!-- context:generated:start -->
## Summary

The typed Axios client layer for the frontend. A single shared client (base URL /api, 60s timeout, Bearer token from localStorage) with a silent refresh flow: on 401 it calls /api/auth/refresh with credentials, queues concurrent requests while refreshing, retries with the new token, redirects to /login on failure. Per-feature api objects (auth, autoclip, batchSlice, channelAccounts, config, dashboard, dramas, intervals, monitor, preview, projects, publish, publishMaterial, shortdrama, slice, upload, variants, watermark, wechatDl) wrap it with typed methods. Long timeouts (1-2h) for large uploads, progress callbacks, and FormData multipart for file flows.

## Related

- configures [[dedupe-config-contract]] — sliceApi.run accepts the manual dedupe config produced by DedupeManualConfig.
- part of [[frontend-auth-session]] — client.ts's silent refresh flow and auth.ts's cookie-based login/refresh/logout are the transport for AuthContext.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
