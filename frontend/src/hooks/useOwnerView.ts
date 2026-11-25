import { useEffect, useState } from 'react';

export type OwnerView = 'me' | 'all';

/**
 * 「仅看自己」这颗全局开关（11-24 素材隔离）与**单个列表自己的**归属筛选之间的桥。
 *
 * 用户原话：「加入素材隔离的概念，但默认是要能看到全部的，但是可以加入一个开关或者复选框，
 * 仅看自己。这个仅看自己，不是说仅仅是自己导入的文案，也可以在已有的脚本库里面勾选，然后收藏起来。」
 *
 * 口径：
 * - `scopeMine` 缺省 / false ⇒ `'all'`（**默认看全部**）。这条把 A′（11-07）
 *   「operator 默认落『我的』」那张按角色默认矩阵顶掉了——两处默认迟早打架，
 *   留用户这句话为准；面板里的「我的｜全部」单选仍然可改，只是初始值统一由开关给。
 * - `scopeMine` true ⇒ `'me'`。各列表的 `owner=me` 含义由后端定：素材＝我导入的，
 *   脚本＝**我写的＋我收藏的**，生产单/成片＝我这条链上的。
 * - 开关翻动时**同步**下面所有列表（含已经挂载的面板）：用户点一下开关，
 *   期望是"整个库收成我的"，不是"只有下一个新挂载的页签才生效"。
 * - 返回值第二项是面板自己的 setter：用户在面板里手动切「我的｜全部」只影响那一屏，
 *   不会回写全局开关——全局开关是"默认怎么摆"，面板筛选是"这一屏我要看一眼对面"。
 */
export function useOwnerView(scopeMine?: boolean): [OwnerView, (v: OwnerView) => void] {
  const [ownerView, setOwnerView] = useState<OwnerView>(scopeMine ? 'me' : 'all');
  useEffect(() => {
    setOwnerView(scopeMine ? 'me' : 'all');
  }, [scopeMine]);
  return [ownerView, setOwnerView];
}
