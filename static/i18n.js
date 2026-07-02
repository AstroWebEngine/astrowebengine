/* ═══════════════════════════════════════════════════
   AstroWebEngine — Internationalization
   Supported: en, es, fr, de, pt
   ═══════════════════════════════════════════════════ */

const LANGUAGES = [
  { id: 'en', name: 'English' },
  { id: 'es', name: 'Espanol' },
  { id: 'fr', name: 'Francais' },
  { id: 'de', name: 'Deutsch' },
  { id: 'pt', name: 'Portugues' },
];

let _currentLang = localStorage.getItem('awe_lang') || 'en';

function setLanguage(lang) {
  _currentLang = lang;
  localStorage.setItem('awe_lang', lang);
  applyStaticTranslations();
  // Refresh dynamic content
  if (typeof loadBases === 'function') loadBases();
  if (typeof loadFleets === 'function') loadFleets();
  if (typeof renderAccountContent === 'function') renderAccountContent();
  if (typeof loadNewsTicker === 'function') loadNewsTicker();
}

function t(key, ...args) {
  const dict = TRANSLATIONS[_currentLang] || TRANSLATIONS['en'];
  // A ruleset can override UI labels (e.g. nav.galaxy -> "Galaxy") via the game
  // definition's `ui.labels`, so the shell speaks the active game's vocabulary
  // instead of one hardcoded set. Definition override > translation > key.
  const override = window.AWE_CONFIG && window.AWE_CONFIG.ui
    && window.AWE_CONFIG.ui.labels && window.AWE_CONFIG.ui.labels[key];
  let str = override || dict[key] || TRANSLATIONS['en'][key] || key;
  // Simple placeholder replacement: {0}, {1}, etc.
  for (let i = 0; i < args.length; i++) {
    str = str.replace(`{${i}}`, args[i]);
  }
  return str;
}

// Translate a game term (ship/building/tech/defense/terrain name)
// Falls back to English name if no translation exists
function tName(englishName) {
  if (_currentLang === 'en') return englishName;
  const dict = GAME_TERMS[_currentLang];
  if (!dict) return englishName;
  return dict[englishName] || englishName;
}

function applyStaticTranslations() {
  // Top header + Tools dropdown (neutral shell) — same onclick-keyed labels
  document.querySelectorAll('#top-header .awe-btn, #awe-tools-menu .awe-btn').forEach(el => {
    const oc = el.getAttribute('onclick') || '';
    const href = el.getAttribute('href') || '';
    if (oc.includes("'rankings'")) {
      // Only the top-header copy carries the live rank-count span (unique id);
      // the Tools-menu copy gets the plain label.
      if (el.closest('#top-header')) el.innerHTML = t('nav.ranks') + ' <span class="comment" id="hud-rank-count"></span>';
      else el.textContent = t('nav.ranks');
    }
    else if (oc.includes("'tutorial'")) el.textContent = t('nav.help');
    else if (oc.includes('openShipSpecsModal')) el.textContent = t('nav.tables');
    else if (oc.includes('openBugReportModal')) el.textContent = t('nav.report');
    else if (oc.includes('doLogout')) el.textContent = t('nav.logout');
    else if (href.includes('/admin')) el.textContent = t('nav.admin');
  });

  // Main nav buttons
  document.querySelectorAll('.main-header-nav .awe-nav-btn').forEach(el => {
    const tab = el.dataset.tab;
    if (tab) el.textContent = t('nav.' + tab);
  });

  // Info bar
  document.querySelectorAll('.main-header-infobox .awe-info-btn').forEach(el => {
    const oc = el.getAttribute('onclick') || '';
    if (oc.includes("'account')") && !oc.includes('credits')) el.textContent = t('nav.account');
    else if (oc.includes("'guild'")) el.textContent = t('nav.guild');
  });

  // Header stat labels
  const labels = { 'Lvl': 'hud.level', 'Econ': 'hud.econ', 'Fleet': 'hud.fleet', 'Tech': 'hud.tech', 'XP': 'hud.xp' };
  document.querySelectorAll('.hlabel').forEach(el => {
    for (const [eng, key] of Object.entries(labels)) {
      if (el.id === 'hud-username') continue;
      if (el.textContent.trim() === eng || el.dataset.i18n === key) {
        el.dataset.i18n = key;
        el.textContent = t(key);
      }
    }
  });

  // Slide panels
  const notesTitle = document.querySelector('#notes-panel .panel-title');
  if (notesTitle) notesTitle.textContent = t('panel.notes');
  const bmTitle = document.querySelector('#bookmarks-panel .panel-title');
  if (bmTitle) bmTitle.textContent = t('panel.bookmarks');
  const notesBtn = document.querySelector('#notes-panel .btn-primary');
  if (notesBtn) notesBtn.textContent = t('btn.saveNotes');
  const notesArea = document.getElementById('player-notes');
  if (notesArea) notesArea.placeholder = t('notes.placeholder');

  // Mobile bottom nav
  document.querySelectorAll('.mobile-nav-btn').forEach(el => {
    const tab = el.dataset.tab;
    const label = el.querySelector('.mobile-nav-label');
    if (label && tab) {
      if (tab === 'more') label.textContent = t('nav.more');
      else label.textContent = t('nav.' + tab);
    }
  });

  // Mobile more menu
  document.querySelectorAll('.mobile-more-item').forEach(el => {
    const oc = el.getAttribute('onclick') || '';
    if (oc.includes("'commanders'")) el.textContent = t('nav.commanders');
    else if (oc.includes("'rankings'")) el.textContent = t('nav.ranks');
    else if (oc.includes("'messages'")) el.innerHTML = t('nav.messages') + ' <span class="notif-badge" id="mobile-notif-badge" style="display:none;">0</span>';
    else if (oc.includes("'account'")) el.textContent = t('nav.account');
    else if (oc.includes("'guild'")) el.textContent = t('nav.guild');
    else if (oc.includes("'tutorial'")) el.textContent = t('nav.help');
    else if (oc.includes('openShipSpecsModal')) el.textContent = t('nav.tables');
    else if (oc.includes('openBugReportModal')) el.textContent = t('nav.reportBug');
    else if (oc.includes('doLogout')) el.textContent = t('nav.logout');
  });

  // Account sidebar
  const acctSidebarMap = {
    overview: 'account.overview', profile: 'account.profile',
    private: 'account.private', display: 'account.display',
    delete: 'account.deleteAccount', credits: 'account.creditsHistory'
  };
  document.querySelectorAll('#account-sidebar .awe-sidebar-link').forEach(el => {
    const oc = el.getAttribute('onclick') || '';
    for (const [sub, key] of Object.entries(acctSidebarMap)) {
      if (oc.includes(`'${sub}'`)) { el.textContent = t(key); break; }
    }
  });
}

// ── Translation Dictionaries ──

const TRANSLATIONS = {

// ════════════════════════════════════════
// ENGLISH (base/fallback)
// ════════════════════════════════════════
en: {
  // Navigation
  'nav.bases': 'Bases',
  'nav.galaxy': 'Map',
  'nav.fleets': 'Fleets',
  'nav.empire': 'Empire',
  'nav.commanders': 'Commanders',
  'nav.ranks': 'Ranks',
  'nav.help': 'Help',
  'nav.tables': 'Tables',
  'nav.report': 'Report',
  'nav.reportBug': 'Report Bug',
  'nav.logout': 'Logout',
  'nav.admin': 'Admin',
  'nav.account': 'Account',
  'nav.messages': 'Messages',
  'nav.guild': 'Guild',
  'nav.more': 'More',

  // HUD
  'hud.level': 'Lvl',
  'hud.econ': 'Econ',
  'hud.fleet': 'Fleet',
  'hud.tech': 'Tech',
  'hud.xp': 'XP',
  'hud.credits': 'cr',
  'hud.newMsg': '{0} New',

  // Buttons
  'btn.build': 'Build',
  'btn.upgrade': 'Upgrade',
  'btn.research': 'Research',
  'btn.cancel': 'Cancel',
  'btn.train': 'Train',
  'btn.move': 'Move',
  'btn.assign': 'Assign',
  'btn.unassign': 'Unassign',
  'btn.dismiss': 'Dismiss',
  'btn.recruit': 'Recruit',
  'btn.send': 'Send',
  'btn.delete': 'Delete',
  'btn.confirm': 'Confirm',
  'btn.close': 'Close',
  'btn.attack': 'Attack',
  'btn.scout': 'Scout',
  'btn.deploy': 'Deploy',
  'btn.recall': 'Recall',
  'btn.transfer': 'Transfer',
  'btn.saveNotes': 'Save Notes',
  'btn.createFleet': 'Create Fleet',
  'btn.mergeFleets': 'Merge Fleets',
  'btn.splitFleet': 'Split Fleet',
  'btn.disbandFleet': 'Disband Fleet',
  'btn.moveFleet': 'Move Fleet',
  'btn.colonize': 'Colonize',

  // Panels & slide panels
  'panel.notes': 'Notes',
  'panel.bookmarks': 'Bookmarks',
  'notes.placeholder': 'Personal notes -- saved per browser...',

  // Base tabs
  'base.structures': 'Structures',
  'base.research': 'Research',
  'base.production': 'Production',
  'base.defenses': 'Defenses',
  'base.trade': 'Trade Routes',
  'base.commander': 'Commander',
  'base.overview': 'Overview',
  'base.astroType': 'Astro Type',
  'base.baseInfo': 'Base Information',
  'base.owner': 'Base Owner',
  'base.income': 'Owner Income',
  'base.units': 'Units',
  'base.availableToBuild': 'Available to Build',
  'base.resources': 'Resources',
  'base.quantity': 'Quantity',

  // Base stats
  'stat.economy': 'Economy',
  'stat.construction': 'Construction',
  'stat.production': 'Production',
  'stat.research': 'Research',
  'stat.energy': 'Energy',
  'stat.population': 'Population',
  'stat.area': 'Area',
  'stat.fertility': 'Fertility',
  'stat.terrain': 'Terrain',

  // Building tiers
  'tier.basic': 'Basic',
  'tier.advanced': 'Advanced',
  'tier.orbital': 'Orbital',

  // Queue
  'queue.building': 'Building Queue',
  'queue.research': 'Research Queue',
  'queue.production': 'Production Queue',
  'queue.defense': 'Defense Queue',
  'queue.empty': 'Queue empty',
  'queue.full': 'Queue full',
  'prod.fast': 'Fast Production (pay +40% to build units in half the time)',
  'queue.position': 'Queue #{0}',
  'queue.active': 'Building...',

  // Fleet
  'fleet.stationed': 'Stationed',
  'fleet.moving': 'Moving',
  'fleet.arriving': 'Arrival',
  'fleet.location': 'Location',
  'fleet.size': 'Size',
  'fleet.ships': 'Ships',
  'fleet.noFleets': 'No fleets yet.',
  'fleet.speed': 'Speed',
  'fleet.hangar': 'Hangar',
  'fleet.selectShips': 'Select Ships',
  'fleet.destination': 'Destination',
  'fleet.travelTime': 'Travel Time',

  // Combat
  'combat.battleReport': 'Battle Report',
  'combat.attacker': 'Attacker',
  'combat.defender': 'Defender',
  'combat.destroyed': 'Destroyed',
  'combat.survived': 'Survived',
  'combat.debris': 'Debris',
  'combat.loot': 'Loot',

  // Commander
  'cmdr.title': 'Commanders',
  'cmdr.capacity': 'Capacity',
  'cmdr.level': 'Level',
  'cmdr.training': 'Training...',
  'cmdr.traveling': 'Traveling...',
  'cmdr.assigned': 'Assigned',
  'cmdr.unassigned': 'Unassigned',
  'cmdr.xpPool': 'XP Pool',
  'cmdr.recruitNew': 'Recruit New Commander',
  'cmdr.useCredits': 'Use Credits',
  'cmdr.useXP': 'Use XP',
  'cmdr.selectBase': 'Select Base',
  'cmdr.noCommanders': 'No commanders recruited yet.',

  // Empire tabs
  'empire.events': 'Events',
  'empire.overview': 'Overview',
  'empire.reports': 'Reports',

  // Account
  'account.overview': 'Overview',
  'account.profile': 'Profile',
  'account.private': 'Private Information',
  'account.display': 'Display',
  'account.deleteAccount': 'Delete Account',
  'account.creditsHistory': 'Credits History',
  'account.credits': 'Credits',
  'account.delete': 'Delete',
  'account.changePw': 'Change Password',
  'account.current': 'Current',
  'account.new': 'New',
  'account.confirmPw': 'Confirm',
  'account.update': 'Update',
  'account.skin': 'Skin',
  'account.language': 'Language',
  'account.animatedTime': 'Display animated server time.',
  'account.notifications': 'Display notifications.',
  'account.nick': 'Nick',
  'account.nickname': 'Nickname',
  'account.playerId': 'Player Id',
  'account.level': 'Level',
  'account.empireIncome': 'Empire Income',
  'account.fleetSize': 'Fleet Size',
  'account.fleetLimit': 'Fleet Limit',
  'account.combatXp': 'Combat Experience',
  'account.score': 'Score',
  'account.joined': 'Joined',
  'account.newbieProtection': 'Newbie Protection',
  'account.active': 'Active',
  'account.nextBaseCost': 'Cost of next base',
  'account.role': 'Role',
  'account.admin': 'Admin',
  'account.player': 'Player',
  'account.email': 'E-mail',
  'account.password': 'Password',

  // Ticker
  'ticker.welcome': 'Welcome to AstroWebEngine — Build your empire across the galaxy!',
  'ticker.vs': '{0} vs. {1} losses: {2} / {3}',

  // Messages
  'msg.inbox': 'Inbox',
  'msg.sentbox': 'Sent',
  'msg.compose': 'Compose',
  'msg.to': 'To',
  'msg.subject': 'Subject',
  'msg.from': 'From',
  'msg.date': 'Date',
  'msg.noMessages': 'Inbox is empty.',
  'msg.deleteSelected': 'Delete selected',
  'msg.autoDelete': 'Messages more than 5 days old will be automatically deleted.',

  // Rankings
  'rank.player': 'Player',
  'rank.guild': 'Guild',
  'rank.level': 'Level',
  'rank.economy': 'Economy',
  'rank.fleet': 'Fleet',
  'rank.technology': 'Technology',
  'rank.experience': 'Experience',

  // Map
  'map.galaxy': 'Galaxy',
  'map.region': 'Region',
  'map.system': 'System',
  'map.planet': 'Planet',
  'map.asteroid': 'Asteroid',
  'map.moon': 'Moon',
  'map.unoccupied': 'Unoccupied',
  'map.occupied': 'Occupied',
  'map.navigate': 'Navigate',
  'map.goTo': 'Go',

  // General
  'general.loading': 'Loading...',
  'general.error': 'Error',
  'general.success': 'Success',
  'general.none': 'None',
  'general.cost': 'Cost',
  'general.time': 'Time',
  'general.level': 'Level',
  'general.max': 'Max',
  'general.available': 'Available',
  'general.required': 'Required',
  'general.viewing': 'viewing {0} messages',
},

// ════════════════════════════════════════
// SPANISH
// ════════════════════════════════════════
es: {
  'nav.bases': 'Bases',
  'nav.galaxy': 'Mapa',
  'nav.fleets': 'Flotas',
  'nav.empire': 'Imperio',
  'nav.commanders': 'Comandantes',
  'nav.ranks': 'Rangos',
  'nav.help': 'Ayuda',
  'nav.tables': 'Tablas',
  'nav.report': 'Reportar',
  'nav.reportBug': 'Reportar Error',
  'nav.logout': 'Salir',
  'nav.admin': 'Admin',
  'nav.account': 'Cuenta',
  'nav.messages': 'Mensajes',
  'nav.guild': 'Gremio',
  'nav.more': 'Mas',

  'hud.level': 'Niv',
  'hud.econ': 'Econ',
  'hud.fleet': 'Flota',
  'hud.tech': 'Tec',
  'hud.xp': 'XP',
  'hud.credits': 'cr',
  'hud.newMsg': '{0} Nuevo',

  'btn.build': 'Construir',
  'btn.upgrade': 'Mejorar',
  'btn.research': 'Investigar',
  'btn.cancel': 'Cancelar',
  'btn.train': 'Entrenar',
  'btn.move': 'Mover',
  'btn.assign': 'Asignar',
  'btn.unassign': 'Desasignar',
  'btn.dismiss': 'Despedir',
  'btn.recruit': 'Reclutar',
  'btn.send': 'Enviar',
  'btn.delete': 'Eliminar',
  'btn.confirm': 'Confirmar',
  'btn.close': 'Cerrar',
  'btn.attack': 'Atacar',
  'btn.scout': 'Explorar',
  'btn.deploy': 'Desplegar',
  'btn.recall': 'Retirar',
  'btn.transfer': 'Transferir',
  'btn.saveNotes': 'Guardar Notas',
  'btn.createFleet': 'Crear Flota',
  'btn.mergeFleets': 'Unir Flotas',
  'btn.splitFleet': 'Dividir Flota',
  'btn.disbandFleet': 'Disolver Flota',
  'btn.moveFleet': 'Mover Flota',
  'btn.colonize': 'Colonizar',

  'panel.notes': 'Notas',
  'panel.bookmarks': 'Marcadores',
  'notes.placeholder': 'Notas personales -- guardadas por navegador...',

  'base.structures': 'Estructuras',
  'base.research': 'Investigacion',
  'base.production': 'Produccion',
  'base.defenses': 'Defensas',
  'base.trade': 'Rutas Comerciales',
  'base.commander': 'Comandante',
  'base.overview': 'General',
  'base.astroType': 'Tipo de Astro',
  'base.baseInfo': 'Informacion de Base',
  'base.owner': 'Propietario',
  'base.income': 'Ingresos',
  'base.units': 'Unidades',
  'base.availableToBuild': 'Disponible para Construir',
  'base.resources': 'Recursos',
  'base.quantity': 'Cantidad',

  'stat.economy': 'Economia',
  'stat.construction': 'Construccion',
  'stat.production': 'Produccion',
  'stat.research': 'Investigacion',
  'stat.energy': 'Energia',
  'stat.population': 'Poblacion',
  'stat.area': 'Area',
  'stat.fertility': 'Fertilidad',
  'stat.terrain': 'Terreno',

  'tier.basic': 'Basico',
  'tier.advanced': 'Avanzado',
  'tier.orbital': 'Orbital',

  'queue.building': 'Cola de Construccion',
  'queue.research': 'Cola de Investigacion',
  'queue.production': 'Cola de Produccion',
  'queue.defense': 'Cola de Defensa',
  'queue.empty': 'Cola vacia',
  'queue.full': 'Cola llena',
  'prod.fast': 'Produccion Rapida (paga +40% para construir en la mitad del tiempo)',
  'queue.position': 'Cola #{0}',
  'queue.active': 'Construyendo...',

  'fleet.stationed': 'Estacionada',
  'fleet.moving': 'En Movimiento',
  'fleet.arriving': 'Llegada',
  'fleet.location': 'Ubicacion',
  'fleet.size': 'Tamano',
  'fleet.ships': 'Naves',
  'fleet.noFleets': 'Sin flotas aun.',
  'fleet.speed': 'Velocidad',
  'fleet.hangar': 'Hangar',
  'fleet.selectShips': 'Seleccionar Naves',
  'fleet.destination': 'Destino',
  'fleet.travelTime': 'Tiempo de Viaje',

  'combat.battleReport': 'Informe de Batalla',
  'combat.attacker': 'Atacante',
  'combat.defender': 'Defensor',
  'combat.destroyed': 'Destruido',
  'combat.survived': 'Sobrevivio',
  'combat.debris': 'Escombros',
  'combat.loot': 'Botin',

  'cmdr.title': 'Comandantes',
  'cmdr.capacity': 'Capacidad',
  'cmdr.level': 'Nivel',
  'cmdr.training': 'Entrenando...',
  'cmdr.traveling': 'Viajando...',
  'cmdr.assigned': 'Asignado',
  'cmdr.unassigned': 'Sin Asignar',
  'cmdr.xpPool': 'XP Disponible',
  'cmdr.recruitNew': 'Reclutar Nuevo Comandante',
  'cmdr.useCredits': 'Usar Creditos',
  'cmdr.useXP': 'Usar XP',
  'cmdr.selectBase': 'Seleccionar Base',
  'cmdr.noCommanders': 'No hay comandantes reclutados aun.',

  'empire.events': 'Eventos',
  'empire.overview': 'General',
  'empire.reports': 'Informes',

  'account.overview': 'General',
  'account.profile': 'Perfil',
  'account.private': 'Informacion Privada',
  'account.display': 'Pantalla',
  'account.deleteAccount': 'Eliminar Cuenta',
  'account.creditsHistory': 'Historial de Creditos',
  'account.credits': 'Creditos',
  'account.delete': 'Eliminar',
  'account.changePw': 'Cambiar Contrasena',
  'account.current': 'Actual',
  'account.new': 'Nueva',
  'account.confirmPw': 'Confirmar',
  'account.update': 'Actualizar',
  'account.skin': 'Tema',
  'account.language': 'Idioma',
  'account.animatedTime': 'Mostrar hora del servidor animada.',
  'account.notifications': 'Mostrar notificaciones.',
  'account.nick': 'Nick',
  'account.nickname': 'Apodo',
  'account.playerId': 'ID de Jugador',
  'account.level': 'Nivel',
  'account.empireIncome': 'Ingreso del Imperio',
  'account.fleetSize': 'Tamano de Flota',
  'account.fleetLimit': 'Limite de Flota',
  'account.combatXp': 'Experiencia de Combate',
  'account.score': 'Puntuacion',
  'account.joined': 'Registrado',
  'account.newbieProtection': 'Proteccion de Novato',
  'account.active': 'Activo',
  'account.nextBaseCost': 'Costo de la proxima base',
  'account.role': 'Rol',
  'account.admin': 'Admin',
  'account.player': 'Jugador',
  'account.email': 'E-mail',
  'account.password': 'Contrasena',
  'ticker.welcome': 'Bienvenido a AstroWebEngine — Construye tu imperio a traves de la galaxia!',
  'ticker.vs': '{0} vs. {1} perdidas: {2} / {3}',

  'msg.inbox': 'Bandeja',
  'msg.sentbox': 'Enviados',
  'msg.compose': 'Escribir',
  'msg.to': 'Para',
  'msg.subject': 'Asunto',
  'msg.from': 'De',
  'msg.date': 'Fecha',
  'msg.noMessages': 'Bandeja vacia.',
  'msg.deleteSelected': 'Eliminar seleccionados',
  'msg.autoDelete': 'Los mensajes de mas de 5 dias se eliminan automaticamente.',

  'rank.player': 'Jugador',
  'rank.guild': 'Gremio',
  'rank.level': 'Nivel',
  'rank.economy': 'Economia',
  'rank.fleet': 'Flota',
  'rank.technology': 'Tecnologia',
  'rank.experience': 'Experiencia',

  'map.galaxy': 'Galaxia',
  'map.region': 'Region',
  'map.system': 'Sistema',
  'map.planet': 'Planeta',
  'map.asteroid': 'Asteroid',
  'map.moon': 'Luna',
  'map.unoccupied': 'Desocupado',
  'map.occupied': 'Ocupado',
  'map.navigate': 'Navegar',
  'map.goTo': 'Ir',

  'general.loading': 'Cargando...',
  'general.error': 'Error',
  'general.success': 'Exito',
  'general.none': 'Ninguno',
  'general.cost': 'Costo',
  'general.time': 'Tiempo',
  'general.level': 'Nivel',
  'general.max': 'Max',
  'general.available': 'Disponible',
  'general.required': 'Requerido',
  'general.viewing': 'viendo {0} mensajes',
},

// ════════════════════════════════════════
// FRENCH
// ════════════════════════════════════════
fr: {
  'nav.bases': 'Bases',
  'nav.galaxy': 'Carte',
  'nav.fleets': 'Flottes',
  'nav.empire': 'Empire',
  'nav.commanders': 'Commandants',
  'nav.ranks': 'Rangs',
  'nav.help': 'Aide',
  'nav.tables': 'Tables',
  'nav.report': 'Signaler',
  'nav.reportBug': 'Signaler un Bug',
  'nav.logout': 'Deconnexion',
  'nav.admin': 'Admin',
  'nav.account': 'Compte',
  'nav.messages': 'Messages',
  'nav.guild': 'Guilde',
  'nav.more': 'Plus',

  'hud.level': 'Niv',
  'hud.econ': 'Eco',
  'hud.fleet': 'Flotte',
  'hud.tech': 'Tech',
  'hud.xp': 'XP',
  'hud.credits': 'cr',
  'hud.newMsg': '{0} Nouveau',

  'btn.build': 'Construire',
  'btn.upgrade': 'Ameliorer',
  'btn.research': 'Rechercher',
  'btn.cancel': 'Annuler',
  'btn.train': 'Entrainer',
  'btn.move': 'Deplacer',
  'btn.assign': 'Assigner',
  'btn.unassign': 'Desassigner',
  'btn.dismiss': 'Renvoyer',
  'btn.recruit': 'Recruter',
  'btn.send': 'Envoyer',
  'btn.delete': 'Supprimer',
  'btn.confirm': 'Confirmer',
  'btn.close': 'Fermer',
  'btn.attack': 'Attaquer',
  'btn.scout': 'Explorer',
  'btn.deploy': 'Deployer',
  'btn.recall': 'Rappeler',
  'btn.transfer': 'Transferer',
  'btn.saveNotes': 'Sauvegarder',
  'btn.createFleet': 'Creer Flotte',
  'btn.mergeFleets': 'Fusionner Flottes',
  'btn.splitFleet': 'Diviser Flotte',
  'btn.disbandFleet': 'Dissoudre Flotte',
  'btn.moveFleet': 'Deplacer Flotte',
  'btn.colonize': 'Coloniser',

  'panel.notes': 'Notes',
  'panel.bookmarks': 'Signets',
  'notes.placeholder': 'Notes personnelles -- sauvegardees par navigateur...',

  'base.structures': 'Structures',
  'base.research': 'Recherche',
  'base.production': 'Production',
  'base.defenses': 'Defenses',
  'base.trade': 'Routes Commerciales',
  'base.commander': 'Commandant',
  'base.overview': 'Apercu',
  'base.astroType': "Type d'Astre",
  'base.baseInfo': 'Informations de Base',
  'base.owner': 'Proprietaire',
  'base.income': 'Revenus',
  'base.units': 'Unites',
  'base.availableToBuild': 'Disponible a Construire',
  'base.resources': 'Ressources',
  'base.quantity': 'Quantite',

  'stat.economy': 'Economie',
  'stat.construction': 'Construction',
  'stat.production': 'Production',
  'stat.research': 'Recherche',
  'stat.energy': 'Energie',
  'stat.population': 'Population',
  'stat.area': 'Zone',
  'stat.fertility': 'Fertilite',
  'stat.terrain': 'Terrain',

  'tier.basic': 'Base',
  'tier.advanced': 'Avance',
  'tier.orbital': 'Orbital',

  'queue.building': 'File de Construction',
  'queue.research': 'File de Recherche',
  'queue.production': 'File de Production',
  'queue.defense': 'File de Defense',
  'queue.empty': 'File vide',
  'queue.full': 'File pleine',
  'prod.fast': 'Production Rapide (payez +40% pour construire en moitie moins de temps)',
  'queue.position': 'File #{0}',
  'queue.active': 'En construction...',

  'fleet.stationed': 'Stationne',
  'fleet.moving': 'En Mouvement',
  'fleet.arriving': 'Arrivee',
  'fleet.location': 'Emplacement',
  'fleet.size': 'Taille',
  'fleet.ships': 'Vaisseaux',
  'fleet.noFleets': 'Pas encore de flottes.',
  'fleet.speed': 'Vitesse',
  'fleet.hangar': 'Hangar',
  'fleet.selectShips': 'Choisir Vaisseaux',
  'fleet.destination': 'Destination',
  'fleet.travelTime': 'Temps de Trajet',

  'combat.battleReport': 'Rapport de Bataille',
  'combat.attacker': 'Attaquant',
  'combat.defender': 'Defenseur',
  'combat.destroyed': 'Detruit',
  'combat.survived': 'Survecus',
  'combat.debris': 'Debris',
  'combat.loot': 'Butin',

  'cmdr.title': 'Commandants',
  'cmdr.capacity': 'Capacite',
  'cmdr.level': 'Niveau',
  'cmdr.training': 'Entrainement...',
  'cmdr.traveling': 'En voyage...',
  'cmdr.assigned': 'Assigne',
  'cmdr.unassigned': 'Non assigne',
  'cmdr.xpPool': 'XP Disponible',
  'cmdr.recruitNew': 'Recruter un Commandant',
  'cmdr.useCredits': 'Utiliser Credits',
  'cmdr.useXP': 'Utiliser XP',
  'cmdr.selectBase': 'Choisir Base',
  'cmdr.noCommanders': 'Aucun commandant recrute.',

  'empire.events': 'Evenements',
  'empire.overview': 'Apercu',
  'empire.reports': 'Rapports',

  'account.overview': 'Apercu',
  'account.profile': 'Profil',
  'account.private': 'Informations Privees',
  'account.display': 'Affichage',
  'account.deleteAccount': 'Supprimer le Compte',
  'account.creditsHistory': 'Historique des Credits',
  'account.credits': 'Credits',
  'account.delete': 'Supprimer',
  'account.changePw': 'Changer le Mot de Passe',
  'account.current': 'Actuel',
  'account.new': 'Nouveau',
  'account.confirmPw': 'Confirmer',
  'account.update': 'Mettre a Jour',
  'account.skin': 'Theme',
  'account.language': 'Langue',
  'account.animatedTime': "Afficher l'heure du serveur animee.",
  'account.notifications': 'Afficher les notifications.',
  'account.nick': 'Pseudo',
  'account.nickname': 'Pseudo',
  'account.playerId': 'ID Joueur',
  'account.level': 'Niveau',
  'account.empireIncome': "Revenu de l'Empire",
  'account.fleetSize': 'Taille de Flotte',
  'account.fleetLimit': 'Limite de Flotte',
  'account.combatXp': 'Experience de Combat',
  'account.score': 'Score',
  'account.joined': 'Inscription',
  'account.newbieProtection': 'Protection Debutant',
  'account.active': 'Actif',
  'account.nextBaseCost': 'Cout de la prochaine base',
  'account.role': 'Role',
  'account.admin': 'Admin',
  'account.player': 'Joueur',
  'account.email': 'E-mail',
  'account.password': 'Mot de Passe',
  'ticker.welcome': 'Bienvenue sur AstroWebEngine — Construisez votre empire a travers la galaxie!',
  'ticker.vs': '{0} vs. {1} pertes: {2} / {3}',

  'msg.inbox': 'Boite de Reception',
  'msg.sentbox': 'Envoyes',
  'msg.compose': 'Ecrire',
  'msg.to': 'A',
  'msg.subject': 'Sujet',
  'msg.from': 'De',
  'msg.date': 'Date',
  'msg.noMessages': 'Boite de reception vide.',
  'msg.deleteSelected': 'Supprimer la selection',
  'msg.autoDelete': 'Les messages de plus de 5 jours sont supprimes automatiquement.',

  'rank.player': 'Joueur',
  'rank.guild': 'Guilde',
  'rank.level': 'Niveau',
  'rank.economy': 'Economie',
  'rank.fleet': 'Flotte',
  'rank.technology': 'Technologie',
  'rank.experience': 'Experience',

  'map.galaxy': 'Galaxie',
  'map.region': 'Region',
  'map.system': 'Systeme',
  'map.planet': 'Planete',
  'map.asteroid': 'Asteroid',
  'map.moon': 'Lune',
  'map.unoccupied': 'Inoccupe',
  'map.occupied': 'Occupe',
  'map.navigate': 'Naviguer',
  'map.goTo': 'Aller',

  'general.loading': 'Chargement...',
  'general.error': 'Erreur',
  'general.success': 'Succes',
  'general.none': 'Aucun',
  'general.cost': 'Cout',
  'general.time': 'Temps',
  'general.level': 'Niveau',
  'general.max': 'Max',
  'general.available': 'Disponible',
  'general.required': 'Requis',
  'general.viewing': '{0} messages affiches',
},

// ════════════════════════════════════════
// GERMAN
// ════════════════════════════════════════
de: {
  'nav.bases': 'Basen',
  'nav.galaxy': 'Karte',
  'nav.fleets': 'Flotten',
  'nav.empire': 'Imperium',
  'nav.commanders': 'Kommandanten',
  'nav.ranks': 'Rangliste',
  'nav.help': 'Hilfe',
  'nav.tables': 'Tabellen',
  'nav.report': 'Melden',
  'nav.reportBug': 'Fehler Melden',
  'nav.logout': 'Abmelden',
  'nav.admin': 'Admin',
  'nav.account': 'Konto',
  'nav.messages': 'Nachrichten',
  'nav.guild': 'Gilde',
  'nav.more': 'Mehr',

  'hud.level': 'Stufe',
  'hud.econ': 'Wirt',
  'hud.fleet': 'Flotte',
  'hud.tech': 'Tech',
  'hud.xp': 'EP',
  'hud.credits': 'cr',
  'hud.newMsg': '{0} Neu',

  'btn.build': 'Bauen',
  'btn.upgrade': 'Ausbauen',
  'btn.research': 'Forschen',
  'btn.cancel': 'Abbrechen',
  'btn.train': 'Trainieren',
  'btn.move': 'Bewegen',
  'btn.assign': 'Zuweisen',
  'btn.unassign': 'Absetzen',
  'btn.dismiss': 'Entlassen',
  'btn.recruit': 'Rekrutieren',
  'btn.send': 'Senden',
  'btn.delete': 'Loschen',
  'btn.confirm': 'Bestatigen',
  'btn.close': 'Schliessen',
  'btn.attack': 'Angreifen',
  'btn.scout': 'Erkunden',
  'btn.deploy': 'Einsetzen',
  'btn.recall': 'Zuruckrufen',
  'btn.transfer': 'Ubertragen',
  'btn.saveNotes': 'Notizen Speichern',
  'btn.createFleet': 'Flotte Erstellen',
  'btn.mergeFleets': 'Flotten Vereinen',
  'btn.splitFleet': 'Flotte Teilen',
  'btn.disbandFleet': 'Flotte Auflosen',
  'btn.moveFleet': 'Flotte Bewegen',
  'btn.colonize': 'Kolonisieren',

  'panel.notes': 'Notizen',
  'panel.bookmarks': 'Lesezeichen',
  'notes.placeholder': 'Personliche Notizen -- im Browser gespeichert...',

  'base.structures': 'Gebaude',
  'base.research': 'Forschung',
  'base.production': 'Produktion',
  'base.defenses': 'Verteidigung',
  'base.trade': 'Handelsrouten',
  'base.commander': 'Kommandant',
  'base.overview': 'Ubersicht',
  'base.astroType': 'Astrotyp',
  'base.baseInfo': 'Basisinformationen',
  'base.owner': 'Besitzer',
  'base.income': 'Einkommen',
  'base.units': 'Einheiten',
  'base.availableToBuild': 'Verfugbar zum Bauen',
  'base.resources': 'Ressourcen',
  'base.quantity': 'Menge',

  'stat.economy': 'Wirtschaft',
  'stat.construction': 'Konstruktion',
  'stat.production': 'Produktion',
  'stat.research': 'Forschung',
  'stat.energy': 'Energie',
  'stat.population': 'Bevolkerung',
  'stat.area': 'Flache',
  'stat.fertility': 'Fruchtbarkeit',
  'stat.terrain': 'Gelande',

  'tier.basic': 'Basis',
  'tier.advanced': 'Fortgeschritten',
  'tier.orbital': 'Orbital',

  'queue.building': 'Bauwarteschlange',
  'queue.research': 'Forschungswarteschlange',
  'queue.production': 'Produktionswarteschlange',
  'queue.defense': 'Verteidigungswarteschlange',
  'queue.empty': 'Warteschlange leer',
  'queue.full': 'Warteschlange voll',
  'prod.fast': 'Schnellproduktion (+40% Kosten, halbe Bauzeit)',
  'queue.position': 'Platz #{0}',
  'queue.active': 'Wird gebaut...',

  'fleet.stationed': 'Stationiert',
  'fleet.moving': 'Unterwegs',
  'fleet.arriving': 'Ankunft',
  'fleet.location': 'Standort',
  'fleet.size': 'Grosse',
  'fleet.ships': 'Schiffe',
  'fleet.noFleets': 'Noch keine Flotten.',
  'fleet.speed': 'Geschwindigkeit',
  'fleet.hangar': 'Hangar',
  'fleet.selectShips': 'Schiffe Wahlen',
  'fleet.destination': 'Ziel',
  'fleet.travelTime': 'Reisezeit',

  'combat.battleReport': 'Kampfbericht',
  'combat.attacker': 'Angreifer',
  'combat.defender': 'Verteidiger',
  'combat.destroyed': 'Zerstort',
  'combat.survived': 'Uberlebt',
  'combat.debris': 'Trummer',
  'combat.loot': 'Beute',

  'cmdr.title': 'Kommandanten',
  'cmdr.capacity': 'Kapazitat',
  'cmdr.level': 'Stufe',
  'cmdr.training': 'Training...',
  'cmdr.traveling': 'Unterwegs...',
  'cmdr.assigned': 'Zugewiesen',
  'cmdr.unassigned': 'Nicht Zugewiesen',
  'cmdr.xpPool': 'EP Vorrat',
  'cmdr.recruitNew': 'Neuen Kommandanten Rekrutieren',
  'cmdr.useCredits': 'Credits Verwenden',
  'cmdr.useXP': 'EP Verwenden',
  'cmdr.selectBase': 'Basis Wahlen',
  'cmdr.noCommanders': 'Noch keine Kommandanten rekrutiert.',

  'empire.events': 'Ereignisse',
  'empire.overview': 'Ubersicht',
  'empire.reports': 'Berichte',

  'account.overview': 'Ubersicht',
  'account.profile': 'Profil',
  'account.private': 'Private Informationen',
  'account.display': 'Anzeige',
  'account.deleteAccount': 'Konto Loschen',
  'account.creditsHistory': 'Credits-Verlauf',
  'account.credits': 'Credits',
  'account.delete': 'Loschen',
  'account.changePw': 'Passwort Andern',
  'account.current': 'Aktuell',
  'account.new': 'Neu',
  'account.confirmPw': 'Bestatigen',
  'account.update': 'Aktualisieren',
  'account.skin': 'Design',
  'account.language': 'Sprache',
  'account.animatedTime': 'Animierte Serverzeit anzeigen.',
  'account.notifications': 'Benachrichtigungen anzeigen.',
  'account.nick': 'Nick',
  'account.nickname': 'Spitzname',
  'account.playerId': 'Spieler-ID',
  'account.level': 'Stufe',
  'account.empireIncome': 'Imperiumseinkommen',
  'account.fleetSize': 'Flottengrosse',
  'account.fleetLimit': 'Flottenlimit',
  'account.combatXp': 'Kampferfahrung',
  'account.score': 'Punkte',
  'account.joined': 'Beigetreten',
  'account.newbieProtection': 'Anfangerschutz',
  'account.active': 'Aktiv',
  'account.nextBaseCost': 'Kosten der nachsten Basis',
  'account.role': 'Rolle',
  'account.admin': 'Admin',
  'account.player': 'Spieler',
  'account.email': 'E-Mail',
  'account.password': 'Passwort',
  'ticker.welcome': 'Willkommen bei AstroWebEngine — Baue dein Imperium quer durch die Galaxie!',
  'ticker.vs': '{0} vs. {1} Verluste: {2} / {3}',

  'msg.inbox': 'Posteingang',
  'msg.sentbox': 'Gesendet',
  'msg.compose': 'Verfassen',
  'msg.to': 'An',
  'msg.subject': 'Betreff',
  'msg.from': 'Von',
  'msg.date': 'Datum',
  'msg.noMessages': 'Posteingang ist leer.',
  'msg.deleteSelected': 'Ausgewahlte loschen',
  'msg.autoDelete': 'Nachrichten alter als 5 Tage werden automatisch geloscht.',

  'rank.player': 'Spieler',
  'rank.guild': 'Gilde',
  'rank.level': 'Stufe',
  'rank.economy': 'Wirtschaft',
  'rank.fleet': 'Flotte',
  'rank.technology': 'Technologie',
  'rank.experience': 'Erfahrung',

  'map.galaxy': 'Galaxie',
  'map.region': 'Region',
  'map.system': 'System',
  'map.planet': 'Planet',
  'map.asteroid': 'Asteroid',
  'map.moon': 'Mond',
  'map.unoccupied': 'Unbewohnt',
  'map.occupied': 'Bewohnt',
  'map.navigate': 'Navigieren',
  'map.goTo': 'Los',

  'general.loading': 'Laden...',
  'general.error': 'Fehler',
  'general.success': 'Erfolg',
  'general.none': 'Keine',
  'general.cost': 'Kosten',
  'general.time': 'Zeit',
  'general.level': 'Stufe',
  'general.max': 'Max',
  'general.available': 'Verfugbar',
  'general.required': 'Erforderlich',
  'general.viewing': '{0} Nachrichten angezeigt',
},

// ════════════════════════════════════════
// PORTUGUESE
// ════════════════════════════════════════
pt: {
  'nav.bases': 'Bases',
  'nav.galaxy': 'Mapa',
  'nav.fleets': 'Frotas',
  'nav.empire': 'Imperio',
  'nav.commanders': 'Comandantes',
  'nav.ranks': 'Rankings',
  'nav.help': 'Ajuda',
  'nav.tables': 'Tabelas',
  'nav.report': 'Reportar',
  'nav.reportBug': 'Reportar Bug',
  'nav.logout': 'Sair',
  'nav.admin': 'Admin',
  'nav.account': 'Conta',
  'nav.messages': 'Mensagens',
  'nav.guild': 'Guilda',
  'nav.more': 'Mais',

  'hud.level': 'Niv',
  'hud.econ': 'Econ',
  'hud.fleet': 'Frota',
  'hud.tech': 'Tec',
  'hud.xp': 'XP',
  'hud.credits': 'cr',
  'hud.newMsg': '{0} Nova',

  'btn.build': 'Construir',
  'btn.upgrade': 'Melhorar',
  'btn.research': 'Pesquisar',
  'btn.cancel': 'Cancelar',
  'btn.train': 'Treinar',
  'btn.move': 'Mover',
  'btn.assign': 'Designar',
  'btn.unassign': 'Remover',
  'btn.dismiss': 'Dispensar',
  'btn.recruit': 'Recrutar',
  'btn.send': 'Enviar',
  'btn.delete': 'Excluir',
  'btn.confirm': 'Confirmar',
  'btn.close': 'Fechar',
  'btn.attack': 'Atacar',
  'btn.scout': 'Explorar',
  'btn.deploy': 'Implantar',
  'btn.recall': 'Recolher',
  'btn.transfer': 'Transferir',
  'btn.saveNotes': 'Salvar Notas',
  'btn.createFleet': 'Criar Frota',
  'btn.mergeFleets': 'Unir Frotas',
  'btn.splitFleet': 'Dividir Frota',
  'btn.disbandFleet': 'Dissolver Frota',
  'btn.moveFleet': 'Mover Frota',
  'btn.colonize': 'Colonizar',

  'panel.notes': 'Notas',
  'panel.bookmarks': 'Favoritos',
  'notes.placeholder': 'Notas pessoais -- salvas por navegador...',

  'base.structures': 'Estruturas',
  'base.research': 'Pesquisa',
  'base.production': 'Producao',
  'base.defenses': 'Defesas',
  'base.trade': 'Rotas Comerciais',
  'base.commander': 'Comandante',
  'base.overview': 'Visao Geral',
  'base.astroType': 'Tipo de Astro',
  'base.baseInfo': 'Informacoes da Base',
  'base.owner': 'Proprietario',
  'base.income': 'Renda',
  'base.units': 'Unidades',
  'base.availableToBuild': 'Disponivel para Construir',
  'base.resources': 'Recursos',
  'base.quantity': 'Quantidade',

  'stat.economy': 'Economia',
  'stat.construction': 'Construcao',
  'stat.production': 'Producao',
  'stat.research': 'Pesquisa',
  'stat.energy': 'Energia',
  'stat.population': 'Populacao',
  'stat.area': 'Area',
  'stat.fertility': 'Fertilidade',
  'stat.terrain': 'Terreno',

  'tier.basic': 'Basico',
  'tier.advanced': 'Avancado',
  'tier.orbital': 'Orbital',

  'queue.building': 'Fila de Construcao',
  'queue.research': 'Fila de Pesquisa',
  'queue.production': 'Fila de Producao',
  'queue.defense': 'Fila de Defesa',
  'queue.empty': 'Fila vazia',
  'queue.full': 'Fila cheia',
  'prod.fast': 'Producao Rapida (pague +40% para construir na metade do tempo)',
  'queue.position': 'Fila #{0}',
  'queue.active': 'Construindo...',

  'fleet.stationed': 'Estacionada',
  'fleet.moving': 'Em Movimento',
  'fleet.arriving': 'Chegada',
  'fleet.location': 'Localizacao',
  'fleet.size': 'Tamanho',
  'fleet.ships': 'Naves',
  'fleet.noFleets': 'Sem frotas ainda.',
  'fleet.speed': 'Velocidade',
  'fleet.hangar': 'Hangar',
  'fleet.selectShips': 'Selecionar Naves',
  'fleet.destination': 'Destino',
  'fleet.travelTime': 'Tempo de Viagem',

  'combat.battleReport': 'Relatorio de Batalha',
  'combat.attacker': 'Atacante',
  'combat.defender': 'Defensor',
  'combat.destroyed': 'Destruido',
  'combat.survived': 'Sobreviveu',
  'combat.debris': 'Destrocos',
  'combat.loot': 'Saque',

  'cmdr.title': 'Comandantes',
  'cmdr.capacity': 'Capacidade',
  'cmdr.level': 'Nivel',
  'cmdr.training': 'Treinando...',
  'cmdr.traveling': 'Viajando...',
  'cmdr.assigned': 'Designado',
  'cmdr.unassigned': 'Nao Designado',
  'cmdr.xpPool': 'XP Disponivel',
  'cmdr.recruitNew': 'Recrutar Novo Comandante',
  'cmdr.useCredits': 'Usar Creditos',
  'cmdr.useXP': 'Usar XP',
  'cmdr.selectBase': 'Selecionar Base',
  'cmdr.noCommanders': 'Nenhum comandante recrutado ainda.',

  'empire.events': 'Eventos',
  'empire.overview': 'Visao Geral',
  'empire.reports': 'Relatorios',

  'account.overview': 'Visao Geral',
  'account.profile': 'Perfil',
  'account.private': 'Informacoes Privadas',
  'account.display': 'Exibicao',
  'account.deleteAccount': 'Excluir Conta',
  'account.creditsHistory': 'Historico de Creditos',
  'account.credits': 'Creditos',
  'account.delete': 'Excluir',
  'account.changePw': 'Alterar Senha',
  'account.current': 'Atual',
  'account.new': 'Nova',
  'account.confirmPw': 'Confirmar',
  'account.update': 'Atualizar',
  'account.skin': 'Tema',
  'account.language': 'Idioma',
  'account.animatedTime': 'Exibir hora do servidor animada.',
  'account.notifications': 'Exibir notificacoes.',
  'account.nick': 'Nick',
  'account.nickname': 'Apelido',
  'account.playerId': 'ID do Jogador',
  'account.level': 'Nivel',
  'account.empireIncome': 'Renda do Imperio',
  'account.fleetSize': 'Tamanho da Frota',
  'account.fleetLimit': 'Limite da Frota',
  'account.combatXp': 'Experiencia de Combate',
  'account.score': 'Pontuacao',
  'account.joined': 'Registrado',
  'account.newbieProtection': 'Protecao de Novato',
  'account.active': 'Ativo',
  'account.nextBaseCost': 'Custo da proxima base',
  'account.role': 'Funcao',
  'account.admin': 'Admin',
  'account.player': 'Jogador',
  'account.email': 'E-mail',
  'account.password': 'Senha',
  'ticker.welcome': 'Bem-vindo ao AstroWebEngine — Construa seu imperio pela galaxia!',
  'ticker.vs': '{0} vs. {1} perdas: {2} / {3}',

  'msg.inbox': 'Caixa de Entrada',
  'msg.sentbox': 'Enviados',
  'msg.compose': 'Escrever',
  'msg.to': 'Para',
  'msg.subject': 'Assunto',
  'msg.from': 'De',
  'msg.date': 'Data',
  'msg.noMessages': 'Caixa de entrada vazia.',
  'msg.deleteSelected': 'Excluir selecionados',
  'msg.autoDelete': 'Mensagens com mais de 5 dias sao excluidas automaticamente.',

  'rank.player': 'Jogador',
  'rank.guild': 'Guilda',
  'rank.level': 'Nivel',
  'rank.economy': 'Economia',
  'rank.fleet': 'Frota',
  'rank.technology': 'Tecnologia',
  'rank.experience': 'Experiencia',

  'map.galaxy': 'Galaxia',
  'map.region': 'Regiao',
  'map.system': 'Sistema',
  'map.planet': 'Planeta',
  'map.asteroid': 'Asteroid',
  'map.moon': 'Lua',
  'map.unoccupied': 'Desocupado',
  'map.occupied': 'Ocupado',
  'map.navigate': 'Navegar',
  'map.goTo': 'Ir',

  'general.loading': 'Carregando...',
  'general.error': 'Erro',
  'general.success': 'Sucesso',
  'general.none': 'Nenhum',
  'general.cost': 'Custo',
  'general.time': 'Tempo',
  'general.level': 'Nivel',
  'general.max': 'Max',
  'general.available': 'Disponivel',
  'general.required': 'Necessario',
  'general.viewing': 'exibindo {0} mensagens',
},

}; // end TRANSLATIONS

// ════════════════════════════════════════════════════════════
// GAME TERMS — Ship, Building, Tech, Defense, Terrain names
// Key = English name from specs.py, Value = translated name
// ════════════════════════════════════════════════════════════

const GAME_TERMS = {

// ── SPANISH ──
es: {
  // Ships
  'Small Ship 1': 'Small Ship 1', 'Small Ship 2': 'Small Ship 2', 'Small Ship 3': 'Small Ship 3',
  'Small Ship 4': 'Small Ship 4', 'Small Ship 5': 'Small Ship 5', 'Small Ship 6': 'Small Ship 6',
  'Small Ship 7': 'Small Ship 7', 'Medium Ship 1': 'Medium Ship 1', 'Medium Ship 2': 'Medium Ship 2',
  'Small Ship 8': 'Small Ship 8', 'Medium Ship 3': 'Medium Ship 3',
  'Medium Ship 4': 'Medium Ship 4', 'Medium Ship 5': 'Medium Ship 5', 'Medium Ship 6': 'Medium Ship 6',
  'Large Ship 1': 'Large Ship 1', 'Large Ship 2': 'Large Ship 2', 'Large Ship 3': 'Large Ship 3',
  'Large Ship 4': 'Large Ship 4', 'Capital Ship 1': 'Capital Ship 1', 'Capital Ship 2': 'Capital Ship 2',
  'Goods': 'Goods',

  // Buildings
  'Urban Structures': 'Estructuras Urbanas', 'Solar Plants': 'Plantas Solares',
  'Gas Plants': 'Plantas de Gas', 'Fusion Plants': 'Plantas de Fusion',
  'Antimatter Plants': 'Plantas de Antimateria', 'Orbital Plants': 'Plantas Orbitales',
  'Research Labs': 'Laboratorios', 'Metal Refineries': 'Refinerias de Metal',
  'Crystal Mines': 'Minas de Cristal', 'Robotic Factories': 'Fabricas Roboticas',
  'Shipyard': 'Astillero', 'Orbital Shipyard': 'Astillero Orbital',
  'Spaceports': 'Puertos Espaciales', 'Command Centers': 'Centros de Comando',
  'Nanite Factories': 'Fabricas de Nanitos', 'Android Factories': 'Fabricas de Androides',
  'Economic Centers': 'Centros Economicos', 'Terraform': 'Terraformacion',
  'Multi-Level Platforms': 'Plataformas Multinivel', 'Orbital Base': 'Base Orbital',
  'Biosphere Modification': 'Modificacion de Biosfera', 'Capital': 'Capital',
  'Jump Gate': 'Portal de Salto',

  // Technologies
  'Energy': 'Energia', 'Computer': 'Computadora', 'Armour': 'Blindaje',
  'Laser': 'Laser', 'Missiles': 'Misiles', 'Stellar Drive': 'Propulsion Estelar',
  'Plasma': 'Plasma', 'Warp Drive': 'Propulsion Warp', 'Shielding': 'Escudos',
  'Ion': 'Ion', 'Stealth': 'Sigilo', 'Photon': 'Foton',
  'Artificial Intelligence': 'Inteligencia Artificial', 'Disruptor': 'Disruptor',
  'Cybernetics': 'Cibernetica', 'Tachyon Communications': 'Comunicaciones Taquionicas',
  'Anti-Gravity': 'Antigravedad',

  // Defenses
  'Barracks': 'Cuarteles', 'Laser Turrets': 'Torretas Laser',
  'Missile Turrets': 'Torretas de Misiles', 'Plasma Turrets': 'Torretas de Plasma',
  'Ion Turrets': 'Torretas Ionicas', 'Photon Turrets': 'Torretas de Foton',
  'Disruptor Turrets': 'Torretas Disruptor', 'Deflection Shields': 'Escudos de Deflexion',
  'Planetary Shield': 'Escudo Planetario', 'Planetary Ring': 'Anillo Planetario',

  // Terrains
  'Terrain 01': 'Terrain 01', 'Terrain 02': 'Terrain 02', 'Terrain 03': 'Terrain 03',
  'Terrain 04': 'Terrain 04', 'Terrain 05': 'Terrain 05', 'Terrain 06': 'Terrain 06',
  'Terrain 07': 'Terrain 07', 'Terrain 08': 'Terrain 08', 'Terrain 09': 'Terrain 09',
  'Terrain 10': 'Terrain 10', 'Terrain 11': 'Terrain 11', 'Terrain 12': 'Terrain 12',
  'Terrain 13': 'Terrain 13', 'Terrain 14': 'Terrain 14', 'Terrain 15': 'Terrain 15',
  'Terrain Field': 'Terrain Field', 'Body Type 2': 'Body Type 2',
  'Planet': 'Planet', 'Moon': 'Moon',
},

// ── FRENCH ──
fr: {
  // Ships
  'Small Ship 1': 'Small Ship 1', 'Small Ship 2': 'Small Ship 2', 'Small Ship 3': 'Small Ship 3',
  'Small Ship 4': 'Small Ship 4', 'Small Ship 5': 'Small Ship 5', 'Small Ship 6': 'Small Ship 6',
  'Small Ship 7': 'Small Ship 7', 'Medium Ship 1': 'Medium Ship 1', 'Medium Ship 2': 'Medium Ship 2',
  'Small Ship 8': 'Small Ship 8', 'Medium Ship 3': 'Medium Ship 3',
  'Medium Ship 4': 'Medium Ship 4', 'Medium Ship 5': 'Medium Ship 5', 'Medium Ship 6': 'Medium Ship 6',
  'Large Ship 1': 'Large Ship 1', 'Large Ship 2': 'Large Ship 2', 'Large Ship 3': 'Large Ship 3',
  'Large Ship 4': 'Large Ship 4', 'Capital Ship 1': 'Capital Ship 1', 'Capital Ship 2': 'Capital Ship 2',
  'Goods': 'Goods',

  // Buildings
  'Urban Structures': 'Structures Urbaines', 'Solar Plants': 'Centrales Solaires',
  'Gas Plants': 'Centrales a Gaz', 'Fusion Plants': 'Centrales a Fusion',
  'Antimatter Plants': "Centrales d'Antimatiere", 'Orbital Plants': 'Centrales Orbitales',
  'Research Labs': 'Laboratoires', 'Metal Refineries': 'Raffineries de Metal',
  'Crystal Mines': 'Mines de Cristal', 'Robotic Factories': 'Usines Robotiques',
  'Shipyard': 'Chantier Naval', 'Orbital Shipyard': 'Chantier Naval Orbital',
  'Spaceports': 'Spatioports', 'Command Centers': 'Centres de Commandement',
  'Nanite Factories': 'Usines de Nanites', 'Android Factories': "Usines d'Androides",
  'Economic Centers': 'Centres Economiques', 'Terraform': 'Terraformation',
  'Multi-Level Platforms': 'Plateformes Multi-Niveaux', 'Orbital Base': 'Base Orbitale',
  'Biosphere Modification': 'Modification de Biosphere', 'Capital': 'Capitale',
  'Jump Gate': 'Portail de Saut',

  // Technologies
  'Energy': 'Energie', 'Computer': 'Ordinateur', 'Armour': 'Blindage',
  'Laser': 'Laser', 'Missiles': 'Missiles', 'Stellar Drive': 'Propulsion Stellaire',
  'Plasma': 'Plasma', 'Warp Drive': 'Propulsion Warp', 'Shielding': 'Boucliers',
  'Ion': 'Ion', 'Stealth': 'Furtivite', 'Photon': 'Photon',
  'Artificial Intelligence': 'Intelligence Artificielle', 'Disruptor': 'Disrupteur',
  'Cybernetics': 'Cybernetique', 'Tachyon Communications': 'Communications Tachyoniques',
  'Anti-Gravity': 'Anti-Gravite',

  // Defenses
  'Barracks': 'Casernes', 'Laser Turrets': 'Tourelles Laser',
  'Missile Turrets': 'Tourelles de Missiles', 'Plasma Turrets': 'Tourelles de Plasma',
  'Ion Turrets': 'Tourelles Ioniques', 'Photon Turrets': 'Tourelles de Photon',
  'Disruptor Turrets': 'Tourelles Disrupteur', 'Deflection Shields': 'Boucliers de Deflexion',
  'Planetary Shield': 'Bouclier Planetaire', 'Planetary Ring': 'Anneau Planetaire',

  // Terrains
  'Terrain 01': 'Terrain 01', 'Terrain 02': 'Terrain 02', 'Terrain 03': 'Terrain 03',
  'Terrain 04': 'Terrain 04', 'Terrain 05': 'Terrain 05', 'Terrain 06': 'Terrain 06',
  'Terrain 07': 'Terrain 07', 'Terrain 08': 'Terrain 08', 'Terrain 09': 'Terrain 09',
  'Terrain 10': 'Terrain 10', 'Terrain 11': 'Terrain 11', 'Terrain 12': 'Terrain 12',
  'Terrain 13': 'Terrain 13', 'Terrain 14': 'Terrain 14', 'Terrain 15': 'Terrain 15',
  'Terrain Field': 'Terrain Field', 'Body Type 2': 'Body Type 2',
  'Planet': 'Planet', 'Moon': 'Moon',
},

// ── GERMAN ──
de: {
  // Ships (German)
  'Small Ship 1': 'Small Ship 1', 'Small Ship 2': 'Small Ship 2', 'Small Ship 3': 'Small Ship 3',
  'Small Ship 4': 'Small Ship 4', 'Small Ship 5': 'Small Ship 5', 'Small Ship 6': 'Small Ship 6',
  'Small Ship 7': 'Small Ship 7', 'Medium Ship 1': 'Medium Ship 1', 'Medium Ship 2': 'Medium Ship 2',
  'Small Ship 8': 'Small Ship 8', 'Medium Ship 3': 'Medium Ship 3',
  'Medium Ship 4': 'Medium Ship 4', 'Medium Ship 5': 'Medium Ship 5', 'Medium Ship 6': 'Medium Ship 6',
  'Large Ship 1': 'Large Ship 1', 'Large Ship 2': 'Large Ship 2', 'Large Ship 3': 'Large Ship 3',
  'Large Ship 4': 'Large Ship 4', 'Capital Ship 1': 'Capital Ship 1', 'Capital Ship 2': 'Capital Ship 2',
  'Goods': 'Goods',

  // Buildings (German)
  'Urban Structures': 'Stadtstrukturen', 'Solar Plants': 'Solarkraftwerke',
  'Gas Plants': 'Gaskraftwerke', 'Fusion Plants': 'Fusionskraftwerke',
  'Antimatter Plants': 'Antimaterie-Kraftwerke', 'Orbital Plants': 'Orbitale Kraftwerke',
  'Research Labs': 'Forschungslabore', 'Metal Refineries': 'Metallraffinerien',
  'Crystal Mines': 'Kristallminen', 'Robotic Factories': 'Roboterfabriken',
  'Shipyard': 'Werft', 'Orbital Shipyard': 'Orbitale Werft',
  'Spaceports': 'Raumhafen', 'Command Centers': 'Kommandozentralen',
  'Nanite Factories': 'Nanitenfabriken', 'Android Factories': 'Androidenfabriken',
  'Economic Centers': 'Wirtschaftszentren', 'Terraform': 'Terraformung',
  'Multi-Level Platforms': 'Mehrstufige Plattformen', 'Orbital Base': 'Orbitale Basis',
  'Biosphere Modification': 'Biospharen-Modifikation', 'Capital': 'Hauptstadt',
  'Jump Gate': 'Sprungtor',

  // Technologies (German)
  'Energy': 'Energie', 'Computer': 'Computer', 'Armour': 'Panzerung',
  'Laser': 'Laser', 'Missiles': 'Raketen', 'Stellar Drive': 'Stellarer Antrieb',
  'Plasma': 'Plasma', 'Warp Drive': 'Warpantrieb', 'Shielding': 'Schilde',
  'Ion': 'Ionen', 'Stealth': 'Tarnung', 'Photon': 'Photonen',
  'Artificial Intelligence': 'Kunstliche Intelligenz', 'Disruptor': 'Disruptoren',
  'Cybernetics': 'Cybernetik', 'Tachyon Communications': 'Tachyonenkommunikation',
  'Anti-Gravity': 'Anti-Schwerkraft',

  // Defenses
  'Barracks': 'Kasernen', 'Laser Turrets': 'Laserturme',
  'Missile Turrets': 'Raketenturme', 'Plasma Turrets': 'Plasmaturme',
  'Ion Turrets': 'Ionenturme', 'Photon Turrets': 'Photonenturme',
  'Disruptor Turrets': 'Disruptorenturme', 'Deflection Shields': 'Ablenkungsschilde',
  'Planetary Shield': 'Planetarer Schild', 'Planetary Ring': 'Planetarer Ring',

  // Terrains
  'Terrain 01': 'Terrain 01', 'Terrain 02': 'Terrain 02', 'Terrain 03': 'Terrain 03',
  'Terrain 04': 'Terrain 04', 'Terrain 05': 'Terrain 05', 'Terrain 06': 'Terrain 06',
  'Terrain 07': 'Terrain 07', 'Terrain 08': 'Terrain 08', 'Terrain 09': 'Terrain 09',
  'Terrain 10': 'Terrain 10', 'Terrain 11': 'Terrain 11', 'Terrain 12': 'Terrain 12',
  'Terrain 13': 'Terrain 13', 'Terrain 14': 'Terrain 14', 'Terrain 15': 'Terrain 15',
  'Terrain Field': 'Terrain Field', 'Body Type 2': 'Body Type 2',
  'Planet': 'Planet', 'Moon': 'Moon',
},

// ── PORTUGUESE ──
pt: {
  // Ships
  'Small Ship 1': 'Small Ship 1', 'Small Ship 2': 'Small Ship 2', 'Small Ship 3': 'Small Ship 3',
  'Small Ship 4': 'Small Ship 4', 'Small Ship 5': 'Small Ship 5', 'Small Ship 6': 'Small Ship 6',
  'Small Ship 7': 'Small Ship 7', 'Medium Ship 1': 'Medium Ship 1', 'Medium Ship 2': 'Medium Ship 2',
  'Small Ship 8': 'Small Ship 8', 'Medium Ship 3': 'Medium Ship 3',
  'Medium Ship 4': 'Medium Ship 4', 'Medium Ship 5': 'Medium Ship 5', 'Medium Ship 6': 'Medium Ship 6',
  'Large Ship 1': 'Large Ship 1', 'Large Ship 2': 'Large Ship 2', 'Large Ship 3': 'Large Ship 3',
  'Large Ship 4': 'Large Ship 4', 'Capital Ship 1': 'Capital Ship 1', 'Capital Ship 2': 'Capital Ship 2',
  'Goods': 'Goods',

  // Buildings
  'Urban Structures': 'Estruturas Urbanas', 'Solar Plants': 'Usinas Solares',
  'Gas Plants': 'Usinas de Gas', 'Fusion Plants': 'Usinas de Fusao',
  'Antimatter Plants': 'Usinas de Antimateria', 'Orbital Plants': 'Usinas Orbitais',
  'Research Labs': 'Laboratorios', 'Metal Refineries': 'Refinarias de Metal',
  'Crystal Mines': 'Minas de Cristal', 'Robotic Factories': 'Fabricas Roboticas',
  'Shipyard': 'Estaleiro', 'Orbital Shipyard': 'Estaleiro Orbital',
  'Spaceports': 'Portos Espaciais', 'Command Centers': 'Centros de Comando',
  'Nanite Factories': 'Fabricas de Nanitos', 'Android Factories': 'Fabricas de Androides',
  'Economic Centers': 'Centros Economicos', 'Terraform': 'Terraformacao',
  'Multi-Level Platforms': 'Plataformas Multinivel', 'Orbital Base': 'Base Orbital',
  'Biosphere Modification': 'Modificacao de Biosfera', 'Capital': 'Capital',
  'Jump Gate': 'Portal de Salto',

  // Technologies
  'Energy': 'Energia', 'Computer': 'Computador', 'Armour': 'Blindagem',
  'Laser': 'Laser', 'Missiles': 'Misseis', 'Stellar Drive': 'Propulsao Estelar',
  'Plasma': 'Plasma', 'Warp Drive': 'Propulsao Warp', 'Shielding': 'Escudos',
  'Ion': 'Ion', 'Stealth': 'Furtividade', 'Photon': 'Foton',
  'Artificial Intelligence': 'Inteligencia Artificial', 'Disruptor': 'Disruptor',
  'Cybernetics': 'Cibernetica', 'Tachyon Communications': 'Comunicacoes Taquionicas',
  'Anti-Gravity': 'Antigravidade',

  // Defenses
  'Barracks': 'Quarteis', 'Laser Turrets': 'Torretas Laser',
  'Missile Turrets': 'Torretas de Misseis', 'Plasma Turrets': 'Torretas de Plasma',
  'Ion Turrets': 'Torretas Ionicas', 'Photon Turrets': 'Torretas de Foton',
  'Disruptor Turrets': 'Torretas Disruptor', 'Deflection Shields': 'Escudos de Deflexao',
  'Planetary Shield': 'Escudo Planetario', 'Planetary Ring': 'Anel Planetario',

  // Terrains
  'Terrain 01': 'Terrain 01', 'Terrain 02': 'Terrain 02', 'Terrain 03': 'Terrain 03',
  'Terrain 04': 'Terrain 04', 'Terrain 05': 'Terrain 05', 'Terrain 06': 'Terrain 06',
  'Terrain 07': 'Terrain 07', 'Terrain 08': 'Terrain 08', 'Terrain 09': 'Terrain 09',
  'Terrain 10': 'Terrain 10', 'Terrain 11': 'Terrain 11', 'Terrain 12': 'Terrain 12',
  'Terrain 13': 'Terrain 13', 'Terrain 14': 'Terrain 14', 'Terrain 15': 'Terrain 15',
  'Terrain Field': 'Terrain Field', 'Body Type 2': 'Body Type 2',
  'Planet': 'Planet', 'Moon': 'Moon',
},

}; // end GAME_TERMS
