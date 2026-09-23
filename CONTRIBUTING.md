# 协作开发

仓库所有者在 GitHub 仓库的 **Settings → Collaborators → Add people** 邀请合作者；对方接受后即可克隆、拉取和推送。组织仓库请授予 Write 权限。

每个人使用自己的 GitHub 账号和 Git 身份，不共享密码、令牌或 SSH 私钥。

## 第一次使用

在仓库页面点击 Code 复制克隆地址，然后运行：

```bash
git clone <仓库克隆地址>
cd warchest-online
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[web,test]'
.venv/bin/python -m pytest -q
.venv/bin/python -m warchest.web --port 8080
```

需要 Python 3.12 或更高版本。HTTPS 可以通过 `gh auth login` 登录并用 `gh auth setup-git` 配置 Git 认证；也可在 GitHub 中添加自己的 SSH 公钥后使用 SSH 克隆地址。

## 日常开发

```bash
git switch main
git pull --ff-only origin main
git switch -c feature/my-change
# 修改代码并运行相关测试
git add <修改的文件>
git commit -m "Describe the change"
git push -u origin feature/my-change
```

在 GitHub 页面创建 Pull Request，审核合并后，其他人运行 `git switch main`、`git pull --ff-only origin main` 获取更新。每个任务用独立分支，避免多人直接修改 main。分支保护需由仓库所有者在 Settings → Rules 中按团队需要配置。

已有未提交修改时先提交或保存修改，再切换分支和拉取。不要用强制推送覆盖同伴提交。

## 文件范围

提交源码、测试、文档及可公开的规则示例。`.gitignore` 排除了虚拟环境、本地工具、房间数据库、环境变量文件、训练运行目录和模型检查点。每个开发者运行自己的本地房间数据库。

修改规则时增加相应回归测试；修改存档或行动结构时考虑规则版本和旧回放兼容。测试命令及浏览器依赖见 README。训练框架尚未实现，当前 AI 是随机或启发式策略。
