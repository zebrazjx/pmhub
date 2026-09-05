const data = window.resumeData;
const avatarStorageKey = "html-resume-avatar";
const maxAvatarBytes = 2 * 1024 * 1024;

const text = (value) => document.createTextNode(value);

function createElement(tag, className, content) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (content !== undefined) element.append(text(content));
  return element;
}

function renderBasics() {
  document.getElementById("candidate-name").textContent = data.basics.name;
  document.getElementById("candidate-target").textContent = data.basics.intent;
  document.getElementById("candidate-summary").textContent = data.basics.summary;

  const pageTitle = `${data.basics.name} - ${data.basics.title}`;
  document.title = pageTitle;
  document.querySelector('meta[name="description"]').content = `${pageTitle} HTML 简历`;
  document.getElementById("resume").setAttribute("aria-label", `${data.basics.name}简历`);
  document.getElementById("candidate-avatar").alt = `${data.basics.name}头像`;
  document.getElementById("avatar-fallback").textContent =
    [...(data.basics.name || "候")][0] || "候";

  const info = [
    ["社媒ID", data.basics.socialId],
    ["本科院校", data.basics.undergraduate],
    ["硕士院校", data.basics.graduate],
    ["邮箱", data.basics.email],
    ["手机号码", data.basics.phone],
    ["毕业年份", data.basics.graduationYear],
    ["关键词", data.highlights.join(" / ")]
  ];

  const container = document.getElementById("personal-info");
  info.forEach(([label, value]) => {
    const item = createElement("article", "info-item");
    item.append(createElement("strong", "", label));
    item.append(createElement("span", "", value));
    container.append(item);
  });
}

function setAvatar(source) {
  const avatar = document.getElementById("candidate-avatar");
  const fallback = document.getElementById("avatar-fallback");

  if (!source) {
    avatar.hidden = true;
    avatar.removeAttribute("src");
    fallback.hidden = false;
    return;
  }

  avatar.src = source;
  avatar.hidden = false;
  fallback.hidden = true;
}

function renderAvatar() {
  let storedAvatar = "";
  try {
    storedAvatar = localStorage.getItem(avatarStorageKey) || "";
  } catch (_error) {
    storedAvatar = "";
  }
  setAvatar(storedAvatar || data.basics.avatar);
}

function renderInternships() {
  const container = document.querySelector('[data-list="internships"]');

  data.internships.forEach((item) => {
    const article = createElement("article", "timeline-item");
    const header = createElement("header", "item-header");
    const titleWrap = createElement("div");
    titleWrap.append(createElement("h4", "", item.company));
    titleWrap.append(createElement("p", "role", item.role));
    header.append(titleWrap);
    header.append(createElement("time", "", item.period));
    article.append(header);
    article.append(createElement("p", "item-summary", item.summary));

    if (item.achievements.length) {
      const list = createElement("ul", "achievement-list");
      item.achievements.forEach((achievement) => {
        const listItem = createElement("li");
        listItem.append(createElement("strong", "", `${achievement.label}：`));
        listItem.append(text(achievement.text));
        list.append(listItem);
      });
      article.append(list);
    }

    container.append(article);
  });
}

function renderOtherExperience() {
  const container = document.querySelector('[data-list="otherExperience"]');

  data.otherExperience.forEach((item) => {
    const article = createElement("article", "experience-card");
    article.append(createElement("h4", "", item.title));
    article.append(createElement("p", "", item.text));
    if (item.link) {
      let url;
      try {
        url = new URL(item.link);
      } catch (_error) {
        url = null;
      }
      if (url && ["http:", "https:", "mailto:"].includes(url.protocol)) {
        const link = createElement("a", "", item.link);
        link.href = url.href;
        link.target = "_blank";
        link.rel = "noreferrer";
        article.append(link);
      }
    }
    container.append(article);
  });
}

function toMarkdown() {
  const lines = [
    `# ${data.basics.name} - ${data.basics.title}`,
    "",
    data.basics.intent,
    "",
    `- 社媒ID：${data.basics.socialId}`,
    `- 本科院校：${data.basics.undergraduate}`,
    `- 硕士院校：${data.basics.graduate}`,
    `- 邮箱：${data.basics.email}`,
    `- 手机号码：${data.basics.phone}`,
    `- 毕业年份：${data.basics.graduationYear}`,
    "",
    "## 核心关键词",
    ...data.highlights.map((item) => `- ${item}`),
    "",
    "## 实习经历"
  ];

  data.internships.forEach((item) => {
    lines.push("", `### ${item.company} - ${item.role}`, `时间：${item.period}`, "", item.summary);
    item.achievements.forEach((achievement) => {
      lines.push(`- **${achievement.label}：**${achievement.text}`);
    });
  });

  lines.push("", "## 其他经历");
  data.otherExperience.forEach((item) => {
    lines.push("", `### ${item.title}`, item.text);
    if (item.link) lines.push(item.link);
  });

  return lines.join("\n");
}

async function copyToClipboard(value, button) {
  try {
    await navigator.clipboard.writeText(value);
  } catch (_error) {
    const area = document.createElement("textarea");
    area.value = value;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.append(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
  const original = button.textContent;
  button.textContent = "已复制";
  setTimeout(() => {
    button.textContent = original;
  }, 1400);
}

function bindActions() {
  document.getElementById("avatar-upload").addEventListener("change", (event) => {
    const [file] = event.currentTarget.files;
    if (!file) return;
    if (file.size > maxAvatarBytes) {
      window.alert("头像文件请控制在 2 MB 以内。");
      event.currentTarget.value = "";
      return;
    }

    const reader = new FileReader();
    reader.addEventListener("load", () => {
      try {
        localStorage.setItem(avatarStorageKey, reader.result);
      } catch (_error) {
        // The preview still works when localStorage is unavailable or full.
      }
      setAvatar(reader.result);
    });
    reader.readAsDataURL(file);
  });
  document.querySelector('[data-action="clear-avatar"]').addEventListener("click", () => {
    try {
      localStorage.removeItem(avatarStorageKey);
    } catch (_error) {
      // Clearing the visible avatar is sufficient when storage is unavailable.
    }
    document.getElementById("avatar-upload").value = "";
    setAvatar("");
  });
  document.querySelector('[data-action="print"]').addEventListener("click", () => window.print());
  document.querySelector('[data-action="copy-markdown"]').addEventListener("click", (event) => {
    copyToClipboard(toMarkdown(), event.currentTarget);
  });
  document.querySelector('[data-action="copy-json"]').addEventListener("click", (event) => {
    copyToClipboard(JSON.stringify(data, null, 2), event.currentTarget);
  });
}

renderBasics();
renderAvatar();
renderInternships();
renderOtherExperience();
bindActions();
