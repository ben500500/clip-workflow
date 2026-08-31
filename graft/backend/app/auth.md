# backend/app/auth.py · [[auth-session-layer]]

- verify_password · function · L36-L38 — 校验明文密码与 bcrypt 哈希是否匹配。
- get_password_hash · function · L41-L43 — 对明文密码进行 bcrypt 哈希。
- _create_jwt · function · L51-L56 — 通用 JWT 生成器，注入 exp 和 iat 时间戳并用 HS256 签名。
- create_access_token · function · L59-L68 — 生成短期 access_token，标记 type=access 并可选携带 jti 支持会话级失效。
- create_refresh_token · function · L71-L88 — 生成长期 refresh_token，强制注入随机 jti 保证并发登录 token 唯一，并返回哈希与过期时间。
- _hash_token · function · L91-L93 — 对 refresh_token 做 SHA-256 哈希以便安全落库。
- decode_token · function · L96-L115 — 解析并校验 JWT 签名与过期时间，可选校验 token 类型，失败抛 401。
- get_current_user · function · L123-L177 — 从 Authorization header 解析 access token，校验用户存在/启用，并检查 jti 会话是否被吊销。
- require_roles · function · L180-L208 — 返回一个依赖工厂，用于按角色集合限制端点访问。
- role_checker · function · L198-L206 — 校验当前用户角色是否在允许集合内，否则抛 403。
- create_user_session · function · L211-L232 — 创建登录会话并落库，记录 refresh_token 哈希、UA、IP，并通过属性回传明文 token 供本次响应使用。
- get_role_menus · function · L284-L290 — 根据角色名返回可访问的菜单标识符列表，非法角色返回空列表。
- _fernet_key_from_secret · function · L298-L301 — 从任意长度 secret 派生 Fernet 密钥（SHA-256 后 base64 urlsafe 编码）。
- encrypt_cookie · function · L304-L313 — 使用 Fernet(AES-256) 加密 Cookie 明文，空输入直接返回空串。
- decrypt_cookie · function · L316-L322 — 使用 Fernet(AES-256) 解密 Cookie 密文，空输入直接返回空串。
