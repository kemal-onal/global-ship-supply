with open('C:/Users/kemal/OneDrive/Masaüstü/mock-up-avs/mock-up-backup/frontend/src/pages/OrderDetail.jsx', 'r', encoding='utf-8') as f:
    content = f.read()
# Cut inserted panel between markers
start = content.find('          {/* IMPA Catalog Browser')
end = content.find('          {/* RFQs */}')
if start != -1 and end != -1:
    content = content[:start] + content[end:]
# Remove state lines
for line in ['  const [showImpaCatalog, setShowImpaCatalog] = useState(false)\n',
             '  const [impaCatalogSearch, setImpaCatalogSearch] = useState(\'\')\n',
             '  const [catalogImpa, setCatalogImpa] = useState([])\n',
             '  const [typedCodes, setTypedCodes] = useState(new Set())\n']:
    content = content.replace(line, '')
# Remove useEffect block
b1 = content.find('  // Fetch IMPA catalog when panel opens')
if b1 != -1:
    b2 = content.find('  }, [draftItems])', b1)
    if b2 != -1:
        content = content[:b1] + content[b2+len('  }, [draftItems])'):]
with open('C:/Users/kemal/OneDrive/Masaüstü/mock-up-avs/mock-up-backup/frontend/src/pages/OrderDetail.jsx', 'w', encoding='utf-8') as f:
    f.write(content)
print('Reverted')
